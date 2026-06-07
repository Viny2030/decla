"""
scripts/fase1_etl.py
━━━━━━━━━━━━━━━━━━━━
Fase 1 — Ingestión y Normalización de DDJJ
Fuentes: Portal de Datos Abiertos OA (datos.gob.ar) + BCRA (deflactación)

Salidas:
  data/processed/ddjj_normalizada.csv
  data/processed/sujetos_obligados_clean.csv
  data/processed/altas_bajas_clean.csv
"""

import logging
from pathlib import Path

import numpy as np
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
    "sujetos_obligados": "https://infra.datos.gob.ar/catalog/jgm/dataset/32/distribution/32.1/download/sujetos-obligados.csv",
    "ddjj_anuales":      "https://infra.datos.gob.ar/catalog/jgm/dataset/32/distribution/32.2/download/declaraciones-juradas-anuales.csv",
    "altas_bajas":       "https://infra.datos.gob.ar/catalog/jgm/dataset/32/distribution/32.3/download/altas-bajas.csv",
}

BCRA_API = "https://api.bcra.gob.ar/estadisticas/v1/datosvariable/4/2023-01-01/2024-12-31"
TC_FIJO  = 900.0   # fallback si BCRA no responde


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
    # normalizar columnas
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
    # CUIL/CUIT
    for col in [c for c in df.columns if "cuil" in c or "cuit" in c]:
        df[col] = df[col].apply(normalizar_cuil)
    # fechas
    for col in [c for c in df.columns if "fecha" in c or "periodo" in c]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
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


def run_etl() -> pd.DataFrame:
    log.info("=" * 55)
    log.info("FASE 1 — ETL")
    log.info("=" * 55)
    dfs = descargar_fuentes()
    tc  = obtener_tipo_cambio()

    sujetos = limpiar_df(dfs.get("sujetos_obligados", pd.DataFrame()))
    ddjj    = limpiar_df(dfs.get("ddjj_anuales",      pd.DataFrame()))
    cambios = limpiar_df(dfs.get("altas_bajas",        pd.DataFrame()))

    if not ddjj.empty:
        ddjj = deflactar(ddjj, tc)

    if not sujetos.empty:
        sujetos.to_csv(PROC_DIR / "sujetos_obligados_clean.csv", index=False)
    if not ddjj.empty:
        ddjj.to_csv(PROC_DIR / "ddjj_normalizada.csv", index=False)
    if not cambios.empty:
        cambios.to_csv(PROC_DIR / "altas_bajas_clean.csv", index=False)

    log.info(f"Fase 1 OK — DDJJ normalizadas: {len(ddjj)}")
    return ddjj


if __name__ == "__main__":
    run_etl()
