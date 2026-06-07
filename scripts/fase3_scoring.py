"""
scripts/fase3_scoring.py
━━━━━━━━━━━━━━━━━━━━━━━━
Fase 3 — Scoring de Riesgo Institucional (Reglas Deterministas)
  · IVPI — Índice de Variación Patrimonial Injustificada
  · Opacidad — efectivo vs. bancarizado
  · Fuga — activos locales vs. offshore

Salida: data/processed/scoring_riesgo.csv
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="[SCORING] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"

UMBRAL_IVPI_ROJO      = 3.0
UMBRAL_IVPI_AMARILLO  = 1.5
UMBRAL_EFECTIVO_ROJO  = 0.5
UMBRAL_OFFSHORE_ROJO  = 0.2


def _col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def _cargar(nombre: str) -> pd.DataFrame:
    p = PROC_DIR / nombre
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def calcular_ivpi(df: pd.DataFrame) -> pd.DataFrame:
    # Columnas del nuevo dataset datos.jus.gob.ar
    c_act  = _col(df, ["total_bienes_final", "patrimonio_neto_usd", "patrimonio_neto"])
    c_ant  = _col(df, ["total_bienes_inicio", "patrimonio_neto_anterior_usd", "patrimonio_neto_anterior"])
    c_ingr = _col(df, ["total_ingreso_neto_c1234", "ingresos_neto_gastos",
                        "ingresos_declarados", "ingresos_anuales", "ingresos_usd"])

    if not all([c_act, c_ant, c_ingr]):
        log.warning("Sin columnas para IVPI — marcando SIN_DATOS")
        df["ivpi"]         = np.nan
        df["ivpi_bandera"] = "SIN_DATOS"
        return df

    df["pn_actual"] = pd.to_numeric(df[c_act],  errors="coerce")
    df["pn_ant"]    = pd.to_numeric(df[c_ant],   errors="coerce")
    df["ingresos"]  = pd.to_numeric(df[c_ingr],  errors="coerce")
    df["delta_pn"]  = df["pn_actual"] - df["pn_ant"]
    df["ivpi"]      = (df["delta_pn"] / df["ingresos"].replace(0, np.nan)).round(3)

    df["ivpi_bandera"] = df["ivpi"].apply(
        lambda v: "ROJA"    if pd.notna(v) and v > UMBRAL_IVPI_ROJO
        else "AMARILLA"     if pd.notna(v) and v > UMBRAL_IVPI_AMARILLO
        else "VERDE"        if pd.notna(v)
        else "SIN_DATOS"
    )
    r = (df["ivpi_bandera"] == "ROJA").sum()
    a = (df["ivpi_bandera"] == "AMARILLA").sum()
    log.info(f"IVPI: {r} rojas / {a} amarillas")
    return df


def calcular_opacidad(df: pd.DataFrame) -> pd.DataFrame:
    c_ef = _col(df, ["efectivo", "dinero_en_efectivo", "ef"])
    c_pt = _col(df, ["pn_actual", "total_bienes_final", "patrimonio_neto_usd", "patrimonio_neto"])

    if not (c_ef and c_pt):
        df["opacidad_ratio"]   = np.nan
        df["opacidad_bandera"] = "SIN_DATOS"
        return df

    ef = pd.to_numeric(df[c_ef], errors="coerce").fillna(0)
    pt = pd.to_numeric(df[c_pt], errors="coerce").replace(0, np.nan)
    df["opacidad_ratio"]   = (ef / pt).round(3)
    df["opacidad_bandera"] = df["opacidad_ratio"].apply(
        lambda v: "ROJA"  if pd.notna(v) and v > UMBRAL_EFECTIVO_ROJO
        else "VERDE"      if pd.notna(v)
        else "SIN_DATOS"
    )
    log.info(f"Opacidad: {(df['opacidad_bandera']=='ROJA').sum()} con >50% efectivo")
    return df


def calcular_fuga(df: pd.DataFrame) -> pd.DataFrame:
    c_ext = _col(df, ["activos_exterior", "offshore", "exterior"])
    c_pt  = _col(df, ["pn_actual", "total_bienes_final", "patrimonio_neto_usd"])

    if not (c_ext and c_pt):
        df["fuga_ratio"]   = np.nan
        df["fuga_bandera"] = "SIN_DATOS"
        return df

    ext = pd.to_numeric(df[c_ext], errors="coerce").fillna(0)
    pt  = pd.to_numeric(df[c_pt],  errors="coerce").replace(0, np.nan)
    df["fuga_ratio"]   = (ext / pt).round(3)
    df["fuga_bandera"] = df["fuga_ratio"].apply(
        lambda v: "ROJA"  if pd.notna(v) and v > UMBRAL_OFFSHORE_ROJO
        else "VERDE"      if pd.notna(v)
        else "SIN_DATOS"
    )
    log.info(f"Fuga: {(df['fuga_bandera']=='ROJA').sum()} con >20% offshore")
    return df


def calcular_score(df: pd.DataFrame) -> pd.DataFrame:
    def score(row):
        s = 0
        s += 45 if row.get("ivpi_bandera")     == "ROJA"  else 20 if row.get("ivpi_bandera") == "AMARILLA" else 0
        s += 30 if row.get("opacidad_bandera") == "ROJA"  else 0
        s += 25 if row.get("fuga_bandera")     == "ROJA"  else 0
        return min(s, 100)

    df["score_riesgo"] = df.apply(score, axis=1)
    df["nivel_riesgo"] = df["score_riesgo"].apply(
        lambda s: "CRÍTICO" if s >= 70 else "ALTO" if s >= 45 else "MEDIO" if s >= 20 else "BAJO"
    )
    return df


def run_scoring() -> pd.DataFrame:
    log.info("=" * 55)
    log.info("FASE 3 — SCORING")
    log.info("=" * 55)
    df = _cargar("ddjj_normalizada.csv")
    if df.empty:
        log.error("Sin datos. Corré fase1_etl.py primero.")
        return pd.DataFrame()

    df = calcular_ivpi(df)
    df = calcular_opacidad(df)
    df = calcular_fuga(df)
    df = calcular_score(df)

    cols = [c for c in [
        "cuit", "funcionario_apellido_nombre", "organismo", "cargo",
        "sector", "anio", "desde",
        "total_bienes_inicio", "total_bienes_final", "total_ingreso_neto_c1234",
        "ingresos_neto_gastos",
        "pn_actual", "pn_ant", "ingresos", "delta_pn",
        "ivpi", "ivpi_bandera",
        "opacidad_ratio", "opacidad_bandera",
        "fuga_ratio", "fuga_bandera",
        "score_riesgo", "nivel_riesgo",
    ] if c in df.columns]

    salida = df[cols].sort_values("score_riesgo", ascending=False)
    salida.to_csv(PROC_DIR / "scoring_riesgo.csv", index=False)

    for nivel in ["CRÍTICO", "ALTO", "MEDIO", "BAJO"]:
        log.info(f"  {nivel}: {(salida['nivel_riesgo']==nivel).sum()}")
    return salida


if __name__ == "__main__":
    run_scoring()