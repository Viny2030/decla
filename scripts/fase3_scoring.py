import logging
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from scripts.utils_oa import parsear_oa_serie
except ImportError:
    from utils_oa import parsear_oa_serie

logging.basicConfig(level=logging.INFO, format="[SCORING] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"

UMBRAL_IVPI_ROJO     = 3.0
UMBRAL_IVPI_AMARILLO = 1.5
UMBRAL_EFECTIVO_ROJO = 0.5
UMBRAL_OFFSHORE_ROJO = 0.2

TC_POR_ANNO = {2021: 102.75, 2022: 177.16, 2023: 808.45, 2024: 1045.00}
TC_DEFAULT = 1045.00

def _tc_act(s): return s.map(lambda a: TC_POR_ANNO.get(int(a) if pd.notna(a) else 2024, TC_DEFAULT))
def _tc_ant(s): return s.map(lambda a: TC_POR_ANNO.get((int(a)-1) if pd.notna(a) else 2023, TC_POR_ANNO.get(2023)))
def _col(df, cs):
    for c in cs:
        if c in df.columns: return c
    return None
def _cargar(n):
    p = PROC_DIR / n
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()

def calcular_ivpi(df):
    ca_act = _col(df, ["total_bienes_final", "patrimonio_neto"])
    ca_ant = _col(df, ["total_bienes_inicio"])
    ca_ing = _col(df, ["total_ingreso_neto_c1234", "ingresos_neto_gastos"])
    if not all([ca_act, ca_ant, ca_ing]):
        log.warning("Sin columnas ARS para IVPI")
        df["ivpi"] = float("nan"); df["ivpi_bandera"] = "SIN_DATOS"; return df
    ac = _col(df, ["anio", "anno", "periodo", "anio_declaracion"])
    anio = pd.to_numeric(df[ac], errors="coerce").fillna(2024) if ac else pd.Series(2024, index=df.index)
    tca = _tc_act(anio)
    tct = _tc_ant(anio)
    def ars2usd(col, tc):
        if not col or col not in df.columns: return pd.Series(float("nan"), index=df.index)
        a = parsear_oa_serie(df[col]); return (a / tc).where(a.notna())
    df["pn_actual"] = ars2usd(ca_act, tca)
    df["ingresos"]  = ars2usd(ca_ing, tca)
    df["pn_ant"]    = ars2usd(ca_ant, tct)
    df["tc_conversion_usd"] = tca.round(2)
    df["tc_ant_usd"]        = tct.round(2)
    df["delta_pn"] = df["pn_actual"] - df["pn_ant"]
    iv = df["ingresos"].where(df["ingresos"] >= 100.0)
    df["ivpi"] = (df["delta_pn"] / iv.replace(0, float("nan"))).round(3)
    df["ivpi_bandera"] = df["ivpi"].apply(lambda v: "ROJA" if pd.notna(v) and v > UMBRAL_IVPI_ROJO else "AMARILLA" if pd.notna(v) and v > UMBRAL_IVPI_AMARILLO else "VERDE" if pd.notna(v) else "SIN_DATOS")
    log.info(f"IVPI: {(df['ivpi_bandera']=='ROJA').sum()} rojas / {(df['ivpi_bandera']=='AMARILLA').sum()} amarillas")
    return df

def calcular_opacidad(df):
    ce = _col(df, ["efectivo","dinero_en_efectivo","ef"])
    cp = _col(df, ["pn_actual","total_bienes_final","patrimonio_neto_usd","patrimonio_neto"])
    if not (ce and cp):
        df["opacidad_ratio"] = float("nan"); df["opacidad_bandera"] = "SIN_DATOS"; return df
    ef = pd.to_numeric(df[ce], errors="coerce").fillna(0)
    pt = pd.to_numeric(df[cp], errors="coerce").replace(0, float("nan"))
    df["opacidad_ratio"]   = (ef / pt).round(3)
    df["opacidad_bandera"] = df["opacidad_ratio"].apply(lambda v: "ROJA" if pd.notna(v) and v > UMBRAL_EFECTIVO_ROJO else "VERDE" if pd.notna(v) else "SIN_DATOS")
    log.info(f"Opacidad: {(df['opacidad_bandera']=='ROJA').sum()} con >50% efectivo")
    return df

def calcular_fuga(df):
    cx = _col(df, ["activos_exterior","offshore","exterior"])
    cp = _col(df, ["pn_actual","total_bienes_final","patrimonio_neto_usd"])
    if not (cx and cp):
        df["fuga_ratio"] = float("nan"); df["fuga_bandera"] = "SIN_DATOS"; return df
    ext = pd.to_numeric(df[cx], errors="coerce").fillna(0)
    pt  = pd.to_numeric(df[cp], errors="coerce").replace(0, float("nan"))
    df["fuga_ratio"]   = (ext / pt).round(3)
    df["fuga_bandera"] = df["fuga_ratio"].apply(lambda v: "ROJA" if pd.notna(v) and v > UMBRAL_OFFSHORE_ROJO else "VERDE" if pd.notna(v) else "SIN_DATOS")
    log.info(f"Fuga: {(df['fuga_bandera']=='ROJA').sum()} con >20% offshore")
    return df

def calcular_score(df):
    def score(row):
        s  = 45 if row.get("ivpi_bandera") == "ROJA" else 20 if row.get("ivpi_bandera") == "AMARILLA" else 0
        s += 30 if row.get("opacidad_bandera") == "ROJA" else 0
        s += 25 if row.get("fuga_bandera") == "ROJA" else 0
        return min(s, 100)
    df["score_riesgo"] = df.apply(score, axis=1)
    df["nivel_riesgo"] = df["score_riesgo"].apply(lambda s: "CRITICO" if s >= 70 else "ALTO" if s >= 45 else "MEDIO" if s >= 20 else "BAJO")
    return df

def run_scoring():
    log.info("=" * 55)
    log.info("FASE 3 - SCORING")
    log.info("=" * 55)
    df = _cargar("ddjj_normalizada.csv")
    if df.empty:
        log.error("Sin datos. Corre fase1_etl.py primero."); return pd.DataFrame()
    df = calcular_ivpi(df)
    df = calcular_opacidad(df)
    df = calcular_fuga(df)
    df = calcular_score(df)
    cols = [c for c in ["cuit","funcionario_apellido_nombre","organismo","cargo","poder","sector","anio","desde","total_bienes_inicio","total_bienes_final","total_ingreso_neto_c1234","ingresos_neto_gastos","pn_actual","pn_ant","ingresos","delta_pn","tc_conversion_usd","tc_ant_usd","ivpi","ivpi_bandera","opacidad_ratio","opacidad_bandera","fuga_ratio","fuga_bandera","score_riesgo","nivel_riesgo"] if c in df.columns]
    salida = df[cols].sort_values("score_riesgo", ascending=False)
    salida.to_csv(PROC_DIR / "scoring_riesgo.csv", index=False)
    for n in ["CRITICO","ALTO","MEDIO","BAJO"]:
        log.info(f"  {n}: {(salida['nivel_riesgo']==n).sum()}")
    return salida

if __name__ == "__main__":
    run_scoring()