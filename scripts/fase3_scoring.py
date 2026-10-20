import logging
from pathlib import Path
import numpy as np
import pandas as pd

try:
    from scripts.utils_oa import parsear_oa_serie
    from scripts.listas_gafi import riesgo_pais
    from scripts.tipo_cambio import tc_por_anio
except ImportError:
    from utils_oa import parsear_oa_serie
    from listas_gafi import riesgo_pais
    from tipo_cambio import tc_por_anio

logging.basicConfig(level=logging.INFO, format="[SCORING] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"

UMBRAL_IVPI_ROJO     = 3.0
UMBRAL_IVPI_AMARILLO = 1.5
UMBRAL_EFECTIVO_ROJO = 0.5
UMBRAL_OFFSHORE_ROJO = 0.2

# Mismo TC que la fase 1 (data/processed/tipo_cambio.csv, BCRA minorista).
TC_POR_ANNO = tc_por_anio()
TC_DEFAULT = TC_POR_ANNO[max(TC_POR_ANNO)]

def _tc_act(s): return s.map(lambda a: TC_POR_ANNO.get(int(a) if pd.notna(a) else 2024, TC_DEFAULT))
def _tc_ant(s): return s.map(lambda a: TC_POR_ANNO.get((int(a)-1) if pd.notna(a) else 2023, TC_POR_ANNO.get(2023)))
def _col(df, cs):
    for c in cs:
        if c in df.columns: return c
    return None
def _cargar(n):
    p = PROC_DIR / n
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()

# Umbrales de calidad del IVPI
ING_MIN_USD        = 2500.0    # ingresos anuales menores: datos de ingresos incompletos → SIN_DATOS
MATERIALIDAD_USD   = 10000.0   # variación no explicada menor: no se marca (VERDE)


def calcular_ivpi(df):
    """IVPI = variación patrimonial NO explicada / ingresos del año.

    variación no explicada = (patrimonio neto final − patrimonio neto inicial)
                             − diferencia de valuación − herencias
    patrimonio neto        = bienes − deudas
    ingresos               = ingreso neto (cat. 1 a 4) + ingresos no alcanzados

    Todo se calcula en PESOS con los rubros que declara el propio funcionario;
    los dólares son sólo para mostrar (TC minorista BCRA de fin de cada año).

    Cambios respecto de la versión anterior (que marcaba 2.066 filas en rojo):
      - usaba bienes brutos (sin deudas) y no descontaba la diferencia de
        valuación ni las herencias declaradas: en 2024 la inflación (+118 %)
        superó a la devaluación (+29 %) y cualquier patrimonio en pesos que
        sólo se actualizó aparecía "creciendo" en dólares;
      - calculaba IVPI también para DDJJ Iniciales y de Baja, donde la
        variación no es comparable;
      - aceptaba ingresos desde USD 100/año (ingresos no informados → IVPI enorme).
    """
    num = lambda c: (parsear_oa_serie(df[c]).fillna(0) if c in df.columns else pd.Series(0.0, index=df.index))
    bi, di = num("total_bienes_inicio"), num("deudas_inicio")
    bf, dfi = num("total_bienes_final"), num("total_deudas_final")
    if not ("total_bienes_inicio" in df.columns and "total_bienes_final" in df.columns):
        log.warning("Sin columnas de bienes para IVPI")
        df["ivpi"] = float("nan"); df["ivpi_bandera"] = "SIN_DATOS"; return df
    ajustes = num("diferencia_valuacion") + np.maximum(num("bienes_por_herencia"), num("bienes_heredados"))
    ingresos_ars = num("total_ingreso_neto_c1234") + num("ingresos_no_alcanzados")
    no_expl_ars = ((bf - dfi) - (bi - di)) - ajustes

    ac = _col(df, ["anio", "anno", "periodo", "anio_declaracion"])
    anio = pd.to_numeric(df[ac], errors="coerce").fillna(2024) if ac else pd.Series(2024, index=df.index)
    tca, tct = _tc_act(anio), _tc_ant(anio)

    df["pn_actual"] = ((bf - dfi) / tca).round(2)
    df["pn_ant"]    = ((bi - di) / tct).round(2)
    df["ingresos"]  = (ingresos_ars / tca).round(2)
    df["delta_pn"]  = (no_expl_ars / tca).round(2)          # variación NO explicada, USD
    df["ajustes_valuacion_herencia_usd"] = (ajustes / tca).round(2)
    df["tc_conversion_usd"] = tca.round(2)
    df["tc_ant_usd"]        = tct.round(2)

    tipo = df["tipo_declaracion_jurada_descripcion"].astype(str) if "tipo_declaracion_jurada_descripcion" in df.columns \
        else pd.Series("Anual", index=df.index)
    es_anual = tipo.str.strip().str.lower().eq("anual")
    ing_ok   = df["ingresos"] >= ING_MIN_USD
    iv = (no_expl_ars / ingresos_ars.where(ing_ok)).where(es_anual)
    df["ivpi"] = iv.round(3)

    material = df["delta_pn"] >= MATERIALIDAD_USD
    df["ivpi_bandera"] = np.select(
        [~es_anual, ~ing_ok, material & (iv > UMBRAL_IVPI_ROJO), material & (iv > UMBRAL_IVPI_AMARILLO), iv.notna()],
        ["SIN_DATOS", "SIN_DATOS", "ROJA", "AMARILLA", "VERDE"], "SIN_DATOS")
    df["ivpi_motivo"] = np.select(
        [~es_anual, ~ing_ok],
        ["DDJJ " + tipo.str.strip() + ": no comparable", "ingresos declarados incompletos (< USD 2.500/año)"], "")
    log.info(f"IVPI: {(df['ivpi_bandera']=='ROJA').sum()} rojas / {(df['ivpi_bandera']=='AMARILLA').sum()} amarillas")
    return df


def deduplicar(df):
    """Una DDJJ por persona y año: la Anual si existe (si no, Inicial o Baja),
    y dentro de ésa la última rectificativa. Antes había 12.799 filas repetidas
    (misma persona contada y rankeada varias veces)."""
    if "cuit" not in df.columns:
        return df
    tipo = df.get("tipo_declaracion_jurada_descripcion", pd.Series("", index=df.index)).astype(str).str.strip().str.lower()
    df = df.assign(_pref=tipo.eq("anual").astype(int),
                   _rect=pd.to_numeric(df.get("rectificativa", 0), errors="coerce").fillna(0),
                   _id=pd.to_numeric(df.get("dj_id", 0), errors="coerce").fillna(0))
    ac = _col(df, ["anio", "anno", "periodo", "anio_declaracion"]) or "cuit"
    antes = len(df)
    df = (df.sort_values(["cuit", ac, "_pref", "_rect", "_id"])
            .drop_duplicates(["cuit", ac], keep="last")
            .drop(columns=["_pref", "_rect", "_id"]))
    log.info(f"Deduplicado: {antes} filas → {len(df)} (una DDJJ por persona y año)")
    return df


BIENES_MIN_USD = 10000.0   # patrimonios menores: el % de efectivo/exterior no es significativo


def _composicion_bienes():
    """Efectivo y bienes en el exterior al CIERRE, por dj_id, desde el detalle
    de bienes de la OA (ddjj_bienes.csv). El total del cierre coincide con
    total_bienes_final en el 98 % de las DDJJ (importes ya a la parte del titular)."""
    b = _cargar("ddjj_bienes.csv")
    if b.empty or "periodo_inicio_cierre" not in b.columns or "dj_id" not in b.columns:
        return None
    b = b[b["periodo_inicio_cierre"].astype(str).str.strip().str.upper() == "C"]
    if b.empty:
        log.warning("ddjj_bienes.csv sin renglones de cierre (correr fase 1)")
        return None
    imp  = pd.to_numeric(b["bien_importe"], errors="coerce").fillna(0)
    tipo = b["bien_tipo"].astype(str).str.upper()
    dj   = pd.to_numeric(b["dj_id"], errors="coerce")
    # Participaciones en sociedades no cotizantes / empresas propias
    es_soc = tipo.str.contains("PARTICIPACIONES SOCIALES SIN COTIZACION|PARTICIPACIONES SOCIETARIAS|PATRIMONIO DE EMPRESAS")
    g = pd.DataFrame({
        "dj_id":    dj,
        "bienes_c": imp,
        "efectivo": imp.where(tipo.str.contains("EFECTIVO"), 0),
        "exterior": imp.where(tipo.str.contains("EXTERIOR"), 0),
        "participaciones": imp.where(es_soc, 0),
        "n_participaciones": es_soc.astype(int),
    }).groupby("dj_id").sum()
    # País de los bienes del exterior: la descripción trae "-País: Uruguay -..."
    ext = tipo.str.contains("EXTERIOR")
    pais = b.loc[ext, "bien_descripcion"].astype(str).str.extract(r"Pa[ií]s:\s*([^-]+?)\s*(?:-|$)")[0].str.strip()
    pp = pd.DataFrame({"dj_id": dj[ext], "pais": pais}).dropna()
    pp = pp[~pp["pais"].str.upper().str.startswith("OTROS")]
    pp["riesgo"] = pp["pais"].map(riesgo_pais)
    g["paises_exterior"] = pp.groupby("dj_id")["pais"].agg(lambda x: "; ".join(sorted(set(x))))
    orden = {"NEGRA": 2, "GRIS": 1, "": 0}
    g["jurisdiccion_riesgo"] = pp.groupby("dj_id")["riesgo"].agg(lambda x: max(x, key=lambda v: orden[v]))
    g["paises_riesgo"] = pp[pp["riesgo"] != ""].groupby("dj_id")["pais"].agg(lambda x: "; ".join(sorted(set(x))))
    return g


def calcular_opacidad_fuga(df):
    comp = _composicion_bienes() if "dj_id" in df.columns else None
    if comp is None:
        for k in ("opacidad", "fuga"):
            df[k + "_ratio"] = float("nan"); df[k + "_bandera"] = "SIN_DATOS"
        log.warning("Opacidad/fuga: sin detalle de bienes → SIN_DATOS")
        return df
    m = pd.to_numeric(df["dj_id"], errors="coerce").map
    total = m(comp["bienes_c"])
    df["efectivo_usd"] = (m(comp["efectivo"]) / _tc_act(df["anio"])).round(2)
    df["exterior_usd"] = (m(comp["exterior"]) / _tc_act(df["anio"])).round(2)
    df["participaciones_usd"] = (m(comp["participaciones"]) / _tc_act(df["anio"])).round(2)
    df["n_participaciones"]   = m(comp["n_participaciones"]).fillna(0).astype(int)
    df["paises_exterior"]     = m(comp["paises_exterior"]).fillna("")
    df["jurisdiccion_riesgo"] = m(comp["jurisdiccion_riesgo"]).fillna("")
    df["paises_riesgo"]       = m(comp["paises_riesgo"]).fillna("")
    valido = total.notna() & (total / _tc_act(df["anio"]) >= BIENES_MIN_USD)
    df["opacidad_ratio"] = (m(comp["efectivo"]) / total).where(valido).round(3)
    df["fuga_ratio"]     = (m(comp["exterior"]) / total).where(valido).round(3)
    df["opacidad_bandera"] = np.where(~valido, "SIN_DATOS",
                             np.where(df["opacidad_ratio"] > UMBRAL_EFECTIVO_ROJO, "ROJA", "VERDE"))
    df["fuga_bandera"]     = np.where(~valido, "SIN_DATOS",
                             np.where(df["fuga_ratio"] > UMBRAL_OFFSHORE_ROJO, "ROJA", "VERDE"))
    log.info(f"Opacidad: {(df['opacidad_bandera']=='ROJA').sum()} con >50% en efectivo · "
             f"Fuga: {(df['fuga_bandera']=='ROJA').sum()} con >20% en el exterior "
             f"(patrimonios >= USD {BIENES_MIN_USD:,.0f})")
    return df


def calcular_score(df):
    def score(row):
        s  = 45 if row.get("ivpi_bandera") == "ROJA" else 20 if row.get("ivpi_bandera") == "AMARILLA" else 0
        s += 30 if row.get("opacidad_bandera") == "ROJA" else 0
        s += 25 if row.get("fuga_bandera") == "ROJA" else 0
        return min(s, 100)
    df["score_riesgo"] = df.apply(score, axis=1)
    df["nivel_riesgo"] = df["score_riesgo"].apply(lambda s: "CRÍTICO" if s >= 70 else "ALTO" if s >= 45 else "MEDIO" if s >= 20 else "BAJO")
    return df

def run_scoring():
    log.info("=" * 55)
    log.info("FASE 3 - SCORING")
    log.info("=" * 55)
    df = _cargar("ddjj_normalizada.csv")
    if df.empty:
        log.error("Sin datos. Corre fase1_etl.py primero."); return pd.DataFrame()
    # Filas sin año válido (el consolidado 2024 trae una con anio=0 y tipo "0.00"
    # que no es una DDJJ): se descartan en vez de rankearlas.
    ac = _col(df, ["anio", "anno", "periodo", "anio_declaracion"])
    if ac:
        anio = pd.to_numeric(df[ac], errors="coerce")
        invalidas = ~anio.between(2000, 2100)
        if invalidas.any():
            log.warning(f"Descartadas {int(invalidas.sum())} filas sin año válido")
            df = df[~invalidas]
    df = deduplicar(df)
    df = calcular_ivpi(df)
    df = calcular_opacidad_fuga(df)
    df = calcular_score(df)
    cols = [c for c in ["dj_id","cuit","funcionario_apellido_nombre","organismo","cargo","poder","sector","anio","desde","total_bienes_inicio","total_bienes_final","total_ingreso_neto_c1234","ingresos_neto_gastos","tipo_declaracion_jurada_descripcion","pn_actual","pn_ant","ingresos","delta_pn","ajustes_valuacion_herencia_usd","tc_conversion_usd","tc_ant_usd","ivpi","ivpi_bandera","ivpi_motivo","efectivo_usd","exterior_usd","participaciones_usd","n_participaciones","paises_exterior","jurisdiccion_riesgo","paises_riesgo","proveedor_contratista","opacidad_ratio","opacidad_bandera","fuga_ratio","fuga_bandera","score_riesgo","nivel_riesgo"] if c in df.columns]
    # Desempate por CUIT: sin él los empates salían en otro orden en cada
    # corrida y el commit diario reescribía ~32.000 renglones sin cambios.
    salida = df[cols].sort_values(["score_riesgo", "cuit"], ascending=[False, True], kind="mergesort")
    salida.to_csv(PROC_DIR / "scoring_riesgo.csv", index=False)
    for n in ["CRÍTICO","ALTO","MEDIO","BAJO"]:
        log.info(f"  {n}: {(salida['nivel_riesgo']==n).sum()}")
    return salida

if __name__ == "__main__":
    run_scoring()