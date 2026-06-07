"""
fase1_etl.py
━━━━━━━━━━━━
Fase 1 — Ingestión y Normalización de DDJJ
Fuentes: datos.jus.gob.ar (OA - Ministerio de Justicia) + BCRA v2.0

Salidas:
  data/processed/ddjj_normalizada.csv
  data/processed/sujetos_obligados_clean.csv
  data/processed/altas_bajas_clean.csv
"""

import logging
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="[ETL] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR  = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROC_DIR.mkdir(parents=True, exist_ok=True)

ENDPOINTS = {
    "ddjj_anuales": (
        "https://datos.jus.gob.ar/dataset/4680199f-6234-4262-8a2a-8f7993bf784d"
        "/resource/a331ccb8-5c13-447f-9bd6-d8018a4b8a62"
        "/download/declaraciones-juradas-2024-consolidado-al-20251222.csv"
    ),
    "ddjj_bienes": (
        "https://datos.jus.gob.ar/dataset/4680199f-6234-4262-8a2a-8f7993bf784d"
        "/resource/ffa28585-9adb-473e-9627-0ffe1938d288"
        "/download/declaraciones-juradas-bienes-2024-consolidado-al-20251222.csv"
    ),
    "ddjj_deudas": (
        "https://datos.jus.gob.ar/dataset/4680199f-6234-4262-8a2a-8f7993bf784d"
        "/resource/dd1c30e2-e773-47fd-ac80-9afaf3f1baa4"
        "/download/declaraciones-juradas-deudas-2024-consolidado-al-20251222.csv"
    ),
}

BCRA_API = "https://api.bcra.gob.ar/estadisticas/v2.0/datosvariable/4/2023-01-01/2024-12-31"
TC_FIJO  = 900.0


def descargar_fuentes() -> dict[str, pd.DataFrame]:
    dfs = {}
    headers = {"User-Agent": "monitor-ddjj/1.0 (academico)"}
    for nombre, url in ENDPOINTS.items():
        dest = RAW_DIR / f"{nombre}.csv"
        if dest.exists():
            log.info(f"{nombre}: caché local ({dest.stat().st_size // 1024} KB)")
            dfs[nombre] = pd.read_csv(dest, low_memory=False)
            continue
        try:
            log.info(f"Descargando {nombre}...")
            r = requests.get(url, headers=headers, timeout=60)
            r.raise_for_status()
            dest.write_bytes(r.content)
            dfs[nombre] = pd.read_csv(dest, low_memory=False)
            log.info(f"  ✓ {len(dfs[nombre])} registros")
        except Exception as e:
            log.warning(f"  ✗ {nombre}: {e}")
            dfs[nombre] = pd.DataFrame()
    return dfs


def obtener_tipo_cambio() -> float:
    tc_path = RAW_DIR / "tipo_cambio.csv"
    if tc_path.exists():
        try:
            df = pd.read_csv(tc_path)
            return float(df["valor"].iloc[-1])
        except Exception:
            pass
    try:
        r = requests.get(BCRA_API, timeout=30)
        r.raise_for_status()
        data = r.json().get("results", [])
        if data:
            df_tc = pd.DataFrame(data)[["fecha", "valor"]]
            df_tc.to_csv(tc_path, index=False)
            tc = float(df_tc["valor"].iloc[-1])
            log.info(f"TC BCRA: ${tc:.2f}")
            return tc
    except Exception as e:
        log.warning(f"BCRA no disponible: {e} — usando TC fijo ${TC_FIJO}")
    return TC_FIJO


def normalizar_cuil(valor) -> str | None:
    if pd.isna(valor):
        return None
    s = str(valor).replace("-", "").replace(" ", "").strip()
    if len(s) == 11:
        return f"{s[:2]}-{s[2:10]}-{s[10]}"
    return s if s else None


def limpiar_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df.columns = (
        df.columns.str.lower().str.strip()
        .str.replace(r"\s+", "_", regex=True)
        .str.replace(r"[áàä]", "a", regex=True)
        .str.replace(r"[éèë]", "e", regex=True)
        .str.replace(r"[íìï]", "i", regex=True)
        .str.replace(r"[óòö]", "o", regex=True)
        .str.replace(r"[úùü]", "u", regex=True)
        .str.replace("ñ", "n", regex=True)
    )
    for col in [c for c in df.columns if "cuil" in c or "cuit" in c]:
        df[col] = df[col].apply(normalizar_cuil)
    for col in [c for c in df.columns if "fecha" in c or "periodo" in c]:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    antes = len(df)
    df.drop_duplicates(inplace=True)
    if antes - len(df) > 0:
        log.info(f"  Duplicados eliminados: {antes - len(df)}")
    return df


def deflactar(df: pd.DataFrame, tc: float) -> pd.DataFrame:
    cols_mon = [c for c in df.columns if any(
        k in c for k in ["patrimonio", "inmueble", "deposito", "efectivo",
                          "vehiculo", "credito", "deuda", "activo", "pasivo"]
    )]
    for col in cols_mon:
        df[col + "_usd"] = pd.to_numeric(df[col], errors="coerce").apply(
            lambda v: round(v / tc, 2) if pd.notna(v) and v != 0 else None
        )
    if cols_mon:
        log.info(f"  Deflactadas {len(cols_mon)} columnas → USD (TC ${tc:.0f})")
    return df


def extraer_sujetos(ddjj: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ddjj.columns if any(
        k in c for k in ["nombre", "apellido", "cuil", "cuit", "cargo",
                          "organismo", "jurisdiccion", "poder", "funcion"]
    )]
    if not cols:
        return pd.DataFrame()
    return ddjj[cols].drop_duplicates().reset_index(drop=True)


def extraer_altas_bajas(ddjj: pd.DataFrame) -> pd.DataFrame:
    cols_mov = [c for c in ddjj.columns if any(
        k in c for k in ["alta", "baja", "inicio", "fin", "desde", "hasta",
                          "ingreso", "egreso"]
    )]
    cols_id = [c for c in ddjj.columns if "cuil" in c or "cuit" in c]
    cols = list(dict.fromkeys(cols_id + cols_mov))
    if not cols_mov:
        return pd.DataFrame()
    return ddjj[cols].dropna(how="all").drop_duplicates().reset_index(drop=True)


def run_etl() -> pd.DataFrame:
    log.info("=" * 55)
    log.info("FASE 1 — ETL")
    log.info("=" * 55)

    dfs = descargar_fuentes()
    tc  = obtener_tipo_cambio()

    ddjj   = limpiar_df(dfs.get("ddjj_anuales", pd.DataFrame()))
    bienes = limpiar_df(dfs.get("ddjj_bienes",  pd.DataFrame()))
    deudas = limpiar_df(dfs.get("ddjj_deudas",  pd.DataFrame()))

    if not ddjj.empty:
        ddjj = deflactar(ddjj, tc)

        sujetos = extraer_sujetos(ddjj)
        cambios = extraer_altas_bajas(ddjj)

        ddjj.to_csv(PROC_DIR / "ddjj_normalizada.csv", index=False)
        log.info(f"  ✓ ddjj_normalizada.csv — {len(ddjj)} registros")

        if not sujetos.empty:
            sujetos.to_csv(PROC_DIR / "sujetos_obligados_clean.csv", index=False)
            log.info(f"  ✓ sujetos_obligados_clean.csv — {len(sujetos)} registros")

        if not cambios.empty:
            cambios.to_csv(PROC_DIR / "altas_bajas_clean.csv", index=False)
            log.info(f"  ✓ altas_bajas_clean.csv — {len(cambios)} registros")

    if not bienes.empty:
        bienes.to_csv(PROC_DIR / "ddjj_bienes.csv", index=False)
        log.info(f"  ✓ ddjj_bienes.csv — {len(bienes)} registros")

    if not deudas.empty:
        deudas.to_csv(PROC_DIR / "ddjj_deudas.csv", index=False)
        log.info(f"  ✓ ddjj_deudas.csv — {len(deudas)} registros")

    log.info(f"Fase 1 OK — DDJJ normalizadas: {len(ddjj)}")
    return ddjj


if __name__ == "__main__":
    run_etl()
