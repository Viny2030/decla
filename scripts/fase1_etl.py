"""
fase1_etl.py
━━━━━━━━━━━━
Fase 1 — Ingestión y Normalización de DDJJ
Fuentes: datos.jus.gob.ar (OA - Ministerio de Justicia) + BCRA v2.0

Salidas:
  data/processed/ddjj_normalizada.csv
  data/processed/sujetos_obligados_clean.csv
  data/processed/altas_bajas_clean.csv
  data/processed/tabla_judicial.csv
"""

import logging
from pathlib import Path

import pandas as pd
import requests

try:
    from scripts.utils_oa import parsear_oa_serie
except ImportError:
    from utils_oa import parsear_oa_serie

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

# Nómina de magistrados federales (sin DDJJ patrimonial pública)
MAGISTRADOS_URL = (
    "https://datos.jus.gob.ar/dataset/3c18d46e-729e-4973-8efd-f54cab18b7e3"
    "/resource/b12bdbb7-646f-4701-99b7-1109ce919dd5"
    "/download/magistrados-justicia-federal-nacional-jueces-20260605.csv"
)
MAGISTRADOS_CONSULTA = "https://ddjjpp.pjn.gov.ar"  # formulario oficial de solicitud (la DDJJ no se accede por link directo)

# API pública de estadísticas del BCRA v4.0 (sin clave). La v2.0 que se usaba
# devuelve 410 Gone desde 2025 y el ETL caía siempre a un TC fijo de $900.
# Variable 4 = tipo de cambio minorista (promedio vendedor).
BCRA_API = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/4?desde={desde}&hasta={hasta}"
# Respaldo: TC BNA de fin de diciembre (mismo que usa fase3_scoring)
TC_RESPALDO = {2021: 102.75, 2022: 177.16, 2023: 808.45, 2024: 1045.00}


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


def descargar_magistrados() -> pd.DataFrame:
    dest = RAW_DIR / "magistrados_federales.csv"
    if dest.exists():
        log.info(f"magistrados: caché local ({dest.stat().st_size // 1024} KB)")
        return pd.read_csv(dest, low_memory=False)
    try:
        log.info("Descargando nómina magistrados federales...")
        r = requests.get(MAGISTRADOS_URL, headers={"User-Agent": "monitor-ddjj/1.0"}, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        df = pd.read_csv(dest, low_memory=False)
        log.info(f"  ✓ {len(df)} magistrados")
        return df
    except Exception as e:
        log.warning(f"  ✗ magistrados: {e}")
        return pd.DataFrame()


def obtener_tipo_cambio(anio: int = 2024) -> float:
    """TC minorista vendedor del último día hábil de diciembre del año declarado."""
    tc_path = RAW_DIR / f"tipo_cambio_{anio}.csv"
    if tc_path.exists():
        try:
            return float(pd.read_csv(tc_path)["valor"].iloc[0])
        except Exception:
            pass
    try:
        url = BCRA_API.format(desde=f"{anio}-12-01", hasta=f"{anio}-12-31")
        r = requests.get(url, timeout=30, headers={"User-Agent": "monitor-ddjj/1.0"})
        r.raise_for_status()
        res = r.json().get("results", [])
        detalle = res[0].get("detalle", []) if res else []
        if detalle:
            ult = max(detalle, key=lambda d: d["fecha"])
            pd.DataFrame([ult]).to_csv(tc_path, index=False)
            log.info(f"TC BCRA v4.0 ({ult['fecha']}): ${float(ult['valor']):.2f}")
            return float(ult["valor"])
    except Exception as e:
        log.warning(f"BCRA no disponible: {e}")
    tc = TC_RESPALDO.get(anio, TC_RESPALDO[max(TC_RESPALDO)])
    log.warning(f"Usando TC de respaldo ${tc:.2f} (BNA dic-{anio})")
    return tc


def normalizar_cuil(valor) -> str | None:
    if pd.isna(valor):
        return None
    s = str(valor).replace("-", "").replace(" ", "").strip()
    if len(s) == 11:
        return f"{s[:2]}-{s[2:10]}-{s[10]}"
    return s if s else None


def limpiar_df(df: pd.DataFrame, dedup: bool = True) -> pd.DataFrame:
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
    # "periodo_inicio_cierre" vale "I" (inicio) o "C" (cierre): NO es una fecha.
    # Antes se convertía a fecha (todo NaN) y el drop_duplicates de abajo borraba
    # bienes iguales al inicio y al cierre (~100.000 renglones del detalle).
    for col in [c for c in df.columns if ("fecha" in c or "periodo" in c) and c != "periodo_inicio_cierre"]:
        df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    if not dedup:
        return df
    antes = len(df)
    df.drop_duplicates(inplace=True)
    if antes - len(df) > 0:
        log.info(f"  Duplicados eliminados: {antes - len(df)}")
    return df


def quitar_copias_corruptas(df: pd.DataFrame) -> pd.DataFrame:
    """El consolidado 2024 de la OA trae 4.278 DDJJ dos veces: una con montos en
    formato OA ("19875315-00") y otra copia con punto decimal ("198753150.00")
    en la que todo monto terminado en "-00" quedó MULTIPLICADO POR 10.
    Verificado contra el detalle de bienes (la suma coincide con la copia OA).
    Si un dj_id aparece en los dos formatos, se descarta la copia con punto."""
    if df.empty or "dj_id" not in df.columns or "total_bienes_final" not in df.columns:
        return df
    es_oa = df["total_bienes_final"].astype(str).str.strip().str.match(r"^-?\d*-\d+$", na=False)
    con_oa = set(df.loc[es_oa, "dj_id"])
    corrupta = ~es_oa & df["dj_id"].isin(con_oa)
    if corrupta.any():
        log.info(f"  Copias con montos x10 descartadas: {int(corrupta.sum())} (dj_id repetido en formato OA)")
    return df[~corrupta].reset_index(drop=True)


def deflactar(df: pd.DataFrame, tc: float) -> pd.DataFrame:
    """
    Convierte a numérico (resolviendo formato OA "11401021-93" → 11401021.93)
    y genera la columna _usd para cada columna monetaria detectada.

    IMPORTANTE: la columna original (ARS) queda sobrescrita con su versión
    numérica — antes quedaba como string OA crudo, lo que rompía cálculos
    downstream (fase3_scoring.py) en ~88% de las filas.
    """
    cols_mon = [c for c in df.columns if any(
        k in c for k in ["patrimonio", "inmueble", "deposito", "efectivo",
                          "vehiculo", "credito", "deuda", "activo", "pasivo",
                          "bienes", "ingreso"]
    )]

    convertidas = 0
    for col in cols_mon:
        antes_na = df[col].isna().sum()
        df[col] = parsear_oa_serie(df[col])
        nuevos_na = int(df[col].isna().sum() - antes_na)
        if nuevos_na > 0:
            log.warning(f"  {col}: {nuevos_na} valores no convertibles (quedan NaN)")

        df[col + "_usd"] = df[col].apply(
            lambda v: round(v / tc, 2) if pd.notna(v) and v != 0 else None
        )
        convertidas += 1

    if convertidas:
        log.info(f"  Convertidas/deflactadas {convertidas} columnas → ARS numérico + USD (TC ${tc:.0f})")
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


def construir_tabla_judicial(magistrados: pd.DataFrame) -> pd.DataFrame:
    if magistrados.empty:
        return pd.DataFrame()
    df = magistrados.copy()
    df.columns = df.columns.str.lower().str.strip()
    tabla = pd.DataFrame({
        "fuente":            "PODER_JUDICIAL",
        "nombre":            df.get("magistrado_nombre", pd.Series(dtype=str)),
        "dni":               df.get("magistrado_dni",    pd.Series(dtype=str)),
        "genero":            df.get("magistrado_genero", pd.Series(dtype=str)),
        "cargo":             df.get("cargo_tipo",        pd.Series(dtype=str)),
        "organismo":         df.get("organo_nombre",     pd.Series(dtype=str)),
        "camara":            df.get("camara",            pd.Series(dtype=str)),
        "provincia":         df.get("organo_provincia",  pd.Series(dtype=str)),
        "fecha_jura":        df.get("cargo_fecha_jura",  pd.Series(dtype=str)),
        "cobertura":         df.get("cargo_cobertura",   pd.Series(dtype=str)),
        "ddjj_estado":       "NO_DISPONIBLE_PUBLICAMENTE",
        "ddjj_consulta_url": MAGISTRADOS_CONSULTA,
        # Campos adicionales reales del dataset Magistrados-Justicia-Federal-Nacional
        # (mismo resource que MAGISTRADOS_URL), utiles para KPIs/graficos honestos
        # del panel Judicial sin depender de DDJJ patrimonial (no publica).
        "tipo_justicia":       df.get("justicia_federal_o_nacional", pd.Series(dtype=str)),
        "vacante":             df.get("cargo_vacante",       pd.Series(dtype=str)),
        "en_licencia":         df.get("cargo_licencia",      pd.Series(dtype=str)),
        "concurso_en_tramite": df.get("concurso_en_tramite", pd.Series(dtype=str)),
        "presidente_camara":   df.get("presidente_camara",   pd.Series(dtype=str)),
        "norma_fecha":         df.get("norma_fecha",         pd.Series(dtype=str)),
    })
    tabla = tabla[tabla["nombre"].notna() & (tabla["nombre"].astype(str).str.strip() != "")]
    # vacante/en_licencia ausentes -> "NO" (estos registros son cargos cubiertos,
    # no plazas vacantes); el resto de campos opcionales quedan NaN si faltan.
    for col in ["vacante", "en_licencia"]:
        tabla[col] = tabla[col].fillna("NO")
    log.info(f"  ✓ tabla_judicial.csv — {len(tabla)} magistrados")
    return tabla


def run_etl() -> pd.DataFrame:
    log.info("=" * 55)
    log.info("FASE 1 — ETL")
    log.info("=" * 55)

    dfs = descargar_fuentes()
    _dj = dfs.get("ddjj_anuales", pd.DataFrame())
    _anios = pd.to_numeric(_dj["anio"], errors="coerce").dropna() if "anio" in _dj.columns else pd.Series(dtype=float)
    tc  = obtener_tipo_cambio(int(_anios.max()) if len(_anios) else 2024)

    ddjj   = quitar_copias_corruptas(limpiar_df(dfs.get("ddjj_anuales", pd.DataFrame())))
    # Detalle renglón por renglón: dos cajas de ahorro con el mismo saldo son dos bienes.
    bienes = limpiar_df(dfs.get("ddjj_bienes",  pd.DataFrame()), dedup=False)
    deudas = limpiar_df(dfs.get("ddjj_deudas",  pd.DataFrame()), dedup=False)

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

    # Nómina judicial
    magistrados = descargar_magistrados()
    tabla_judicial = construir_tabla_judicial(magistrados)
    if not tabla_judicial.empty:
        tabla_judicial.to_csv(PROC_DIR / "tabla_judicial.csv", index=False)

    log.info(f"Fase 1 OK — DDJJ normalizadas: {len(ddjj)}")
    return ddjj


if __name__ == "__main__":
    run_etl()