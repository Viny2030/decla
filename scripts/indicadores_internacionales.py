"""
scripts/indicadores_internacionales.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
12 indicadores internacionales aplicados a DDJJ argentinas.
Marcos: FATF/GAFI · World Bank CCI · Transparency International CPI · OCDE
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="[INDIC] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"

# ── Constantes internacionales ────────────────────────────────────────────

FATF_CASH_UMBRAL = 0.30
FATF_PEP_CARGOS  = {
    "presidente", "vicepresidente", "ministro", "secretario", "subsecretario",
    "director nacional", "juez", "fiscal", "gobernador", "intendente",
    "senador", "diputado", "legislador",
}
FATF_LISTA_GRIS  = {
    "bulgaria", "camerun", "croacia", "republica del congo",
    "siria", "vietnam", "yemen", "sudafrica",
}
FATF_LISTA_NEGRA = {"corea del norte", "iran", "myanmar"}

WB_AR_PERCENTIL  = 43.8
WB_LAC_PERCENTIL = 49.3
WB_BRECHA_UMBRAL = 10.0

TI_AR_CPI        = 38
TI_VELOCIDAD_BM  = 1.2
TI_SECTORES_RIESGO = {
    "obra publica", "contratos", "licitacion", "concesion",
    "regulacion", "energia", "mineria", "agro", "comunicaciones",
}

OCDE_UMBRAL_ACUM  = 1.5
OCDE_CAMPOS_OBLIG = [
    "inmuebles", "vehiculos", "depositos_bancarios", "efectivo",
    "participaciones_societarias", "deudas", "ingresos_anuales",
]
OCDE_PUERTA_DIAS = 365

PESOS = {
    "A1_pep":           8,
    "A2_beneficial_ow": 7,
    "A3_cash_ratio":    8,
    "A4_jurisdiccion":  7,
    "B1_pares_lac":    10,
    "B2_brecha_sal":   10,
    "C1_velocidad":    10,
    "C2_sector":        5,
    "D1_completitud":   5,
    "D2_conflicto":    13,
    "D3_puerta":       10,
    "D4_evolucion":     7,
}
assert sum(PESOS.values()) == 100

MAXIMOS = {
    "A1_pep": 30, "A2_beneficial_ow": 35, "A3_cash_ratio": 40,
    "A4_jurisdiccion": 40, "B1_pares_lac": 35, "B2_brecha_sal": 30,
    "C1_velocidad": 30, "C2_sector": 15, "D1_completitud": 25,
    "D2_conflicto": 40, "D3_puerta": 30, "D4_evolucion": 35,
}


# ── Helpers ───────────────────────────────────────────────────────────────

def _col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def _cargar(nombre: str) -> pd.DataFrame:
    p = PROC_DIR / nombre
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def _bandera(score: float) -> str:
    if score >= 70: return "ROJA"
    if score >= 40: return "NARANJA"
    if score >= 20: return "AMARILLA"
    return "VERDE"


# ── Grupo A — FATF ────────────────────────────────────────────────────────

def a1_pep(df: pd.DataFrame) -> pd.Series:
    col = _col(df, ["cargo", "funcion", "denominacion_cargo"])
    if not col:
        return pd.Series(0, index=df.index)
    def s(v):
        if pd.isna(v): return 0
        return 30 if any(k in str(v).lower() for k in FATF_PEP_CARGOS) else 0
    return df[col].apply(s)


def a2_beneficial_ow(df: pd.DataFrame) -> pd.Series:
    col_soc = _col(df, ["cuit_sociedad", "participacion_societaria", "sociedad"])
    col_jur = _col(df, ["pais_sociedad", "jurisdiccion", "pais"])
    scores  = pd.Series(0, index=df.index)
    if col_soc:
        tiene = df[col_soc].notna() & (df[col_soc].astype(str).str.strip() != "")
        scores[tiene] = 20
    if col_jur:
        offshore = df[col_jur].astype(str).str.lower().apply(
            lambda v: any(j in v for j in FATF_LISTA_NEGRA | FATF_LISTA_GRIS)
        )
        scores[offshore] = 35
    return scores


def a3_cash_ratio(df: pd.DataFrame) -> pd.Series:
    # efectivo no está en el CSV público — usar proxy: bienes_inicio vs bienes_final
    # Si no hay columna de efectivo, skip (devuelve 0 — correcto, no tenemos el dato)
    c_ef = _col(df, ["efectivo", "dinero_en_efectivo", "ef"])
    # FIX: columnas reales del scoring
    c_pt = _col(df, ["pn_actual", "total_bienes_final_usd", "patrimonio_neto_usd", "total_bienes_final"])
    if not (c_ef and c_pt):
        return pd.Series(0, index=df.index)
    ef   = pd.to_numeric(df[c_ef], errors="coerce").fillna(0)
    pt   = pd.to_numeric(df[c_pt], errors="coerce").replace(0, np.nan)
    ratio = (ef / pt).fillna(0)
    return pd.Series(np.where(
        ratio > FATF_CASH_UMBRAL,
        np.minimum(40, (ratio - FATF_CASH_UMBRAL) * 100),
        0,
    ).astype(float), index=df.index)


def a4_jurisdiccion(df: pd.DataFrame) -> pd.Series:
    col = _col(df, ["pais_activo", "jurisdiccion", "activos_exterior", "pais_sociedad"])
    if not col:
        return pd.Series(0, index=df.index)
    def s(v):
        if pd.isna(v): return 0
        v = str(v).lower()
        if any(j in v for j in FATF_LISTA_NEGRA): return 40
        if any(j in v for j in FATF_LISTA_GRIS):  return 20
        return 0
    return df[col].apply(s)


# ── Grupo B — World Bank ──────────────────────────────────────────────────

def b1_pares_lac(df: pd.DataFrame) -> pd.Series:
    # FIX: columnas reales
    c_pat   = _col(df, ["pn_actual", "total_bienes_final_usd", "patrimonio_neto_usd"])
    c_cargo = _col(df, ["cargo", "funcion", "denominacion_cargo"])
    if not (c_pat and c_cargo):
        log.warning("b1_pares_lac: faltan columnas pn/cargo")
        return pd.Series(0, index=df.index)
    df = df.copy()
    df["_pat"] = pd.to_numeric(df[c_pat], errors="coerce")
    scores = pd.Series(0.0, index=df.index)
    grupos_validos = 0
    for _, grupo in df.groupby(c_cargo):
        vals = grupo["_pat"].dropna()
        if len(vals) < 3:
            continue
        grupos_validos += 1
        p80 = vals.quantile(0.80)
        p95 = vals.quantile(0.95)
        for idx in grupo.index:
            v = grupo.loc[idx, "_pat"]
            if pd.isna(v): continue
            if v >= p95:   scores[idx] = 35
            elif v >= p80: scores[idx] = 20
    log.info(f"b1_pares_lac: {grupos_validos} grupos con ≥3 registros, score medio={scores.mean():.2f}")
    return scores


def b2_brecha_salario(df: pd.DataFrame) -> pd.Series:
    # FIX: columnas reales del scoring — 'ingresos' (USD), 'pn_actual' (USD)
    c_pat  = _col(df, ["pn_actual", "total_bienes_final_usd", "patrimonio_neto_usd"])
    c_sal  = _col(df, ["ingresos", "ingresos_anuales", "remuneracion", "ingresos_neto_gastos_usd"])
    c_años = _col(df, ["anios_cargo", "años_mandato"])
    if not (c_pat and c_sal):
        log.warning(f"b2_brecha_sal: falta c_pat={c_pat} o c_sal={c_sal}")
        return pd.Series(0, index=df.index)
    pat  = pd.to_numeric(df[c_pat], errors="coerce").fillna(0)
    sal  = pd.to_numeric(df[c_sal], errors="coerce").replace(0, np.nan)
    años = pd.to_numeric(df[c_años], errors="coerce").fillna(4) if c_años else pd.Series(4, index=df.index)
    ratio = (pat / (sal * años)).fillna(0)
    result = pd.Series(np.where(
        ratio > WB_BRECHA_UMBRAL,
        np.minimum(30, (ratio - WB_BRECHA_UMBRAL) * 2),
        0,
    ).astype(float), index=df.index)
    log.info(f"b2_brecha_sal: ratio medio={ratio.mean():.1f}, alertas={( ratio > WB_BRECHA_UMBRAL).sum()}")
    return result


# ── Grupo C — TI ──────────────────────────────────────────────────────────

def c1_velocidad(df: pd.DataFrame) -> pd.Series:
    # FIX: ivpi viene del scoring_riesgo.csv mergeado
    col = _col(df, ["ivpi", "ivpi_f3", "indice_variacion"])
    if not col:
        log.warning("c1_velocidad: columna ivpi no encontrada")
        return pd.Series(0, index=df.index)
    ivpi = pd.to_numeric(df[col], errors="coerce").fillna(0)
    bm   = TI_VELOCIDAD_BM
    result = pd.Series(np.where(
        ivpi > bm * 3,  30,
        np.where(ivpi > bm * 2, 20,
        np.where(ivpi > bm,     10, 0))
    ).astype(float), index=df.index)
    log.info(f"c1_velocidad: ivpi medio={ivpi.mean():.2f}, alertas (>bm)={(ivpi > bm).sum()}")
    return result


def c2_sector(df: pd.DataFrame) -> pd.Series:
    col = _col(df, ["organismo", "jurisdiccion", "ministerio"])
    if not col:
        return pd.Series(0, index=df.index)
    def s(v):
        if pd.isna(v): return 0
        return 15 if any(k in str(v).lower() for k in TI_SECTORES_RIESGO) else 0
    return df[col].apply(s)


# ── Grupo D — OCDE ────────────────────────────────────────────────────────

def d1_completitud(df: pd.DataFrame) -> pd.Series:
    campos = [c for c in OCDE_CAMPOS_OBLIG if any(
        c.replace("_", "") in col.replace("_", "") for col in df.columns
    )]
    if not campos:
        return pd.Series(0, index=df.index)
    scores = []
    for _, row in df.iterrows():
        faltantes = sum(
            1 for campo in campos
            if pd.isna(row.get(campo)) or str(row.get(campo, "")).strip() in ("", "0", "nan")
        )
        scores.append(min(25, int(faltantes / len(campos) * 50)))
    return pd.Series(scores, index=df.index)


def d2_conflicto(df: pd.DataFrame) -> pd.Series:
    alertas = _cargar("alertas_conflicto.csv")
    scores  = pd.Series(0, index=df.index)
    if alertas.empty:
        return scores
    cuil_df = _col(df, ["cuil", "cuil_declarante", "cuit"])
    cuil_al = _col(alertas, ["cuil_funcionario"])
    if not (cuil_df and cuil_al):
        return scores
    cuils_r = set(
        alertas[alertas.get("criticidad", pd.Series("")).eq("ROJA")][cuil_al]
        .astype(str).str.replace("-", "")
    )
    cuils_a = set(alertas[cuil_al].astype(str).str.replace("-", "")) - cuils_r
    for idx, row in df.iterrows():
        c = str(row.get(cuil_df, "")).replace("-", "")
        if c in cuils_r:   scores[idx] = 40
        elif c in cuils_a: scores[idx] = 20
    return scores


def d3_puerta_giratoria(df: pd.DataFrame) -> pd.Series:
    alertas = _cargar("alertas_puertas_giratorias.csv")
    scores  = pd.Series(0, index=df.index)
    if alertas.empty:
        return scores
    cuil_df = _col(df, ["cuil", "cuil_declarante", "cuit"])
    cuil_pg = _col(alertas, ["cuil_funcionario"])
    if not (cuil_df and cuil_pg):
        return scores
    cuils = set(alertas[cuil_pg].astype(str).str.replace("-", ""))
    for idx, row in df.iterrows():
        c = str(row.get(cuil_df, "")).replace("-", "")
        if c in cuils:
            scores[idx] = 30
    return scores


def d4_evolucion_ocde(df: pd.DataFrame) -> pd.Series:
    # FIX: columnas reales
    c_act  = _col(df, ["pn_actual", "total_bienes_final_usd", "patrimonio_neto_usd"])
    c_ini  = _col(df, ["pn_ant", "patrimonio_neto_inicial", "pn_inicial", "total_bienes_inicio_usd"])
    c_ingr = _col(df, ["ingresos", "ingresos_anuales", "ingresos_neto_gastos_usd"])
    c_años = _col(df, ["anios_cargo", "años_mandato"])

    if not (c_act and c_ingr):
        log.warning(f"d4_evolucion: falta c_act={c_act} o c_ingr={c_ingr}")
        return pd.Series(0, index=df.index)

    pat_act = pd.to_numeric(df[c_act],  errors="coerce").fillna(0)
    ingr    = pd.to_numeric(df[c_ingr], errors="coerce").replace(0, np.nan)
    años    = pd.to_numeric(df[c_años], errors="coerce").fillna(4) if c_años else pd.Series(4, index=df.index)

    if c_ini:
        pat_ini = pd.to_numeric(df[c_ini], errors="coerce").replace(0, np.nan)
    else:
        # Fallback: usar ivpi si existe
        c_ivpi  = _col(df, ["ivpi", "ivpi_f3"])
        ivpi    = pd.to_numeric(df[c_ivpi], errors="coerce").fillna(0) if c_ivpi else pd.Series(0, index=df.index)
        pat_ini = pat_act / (1 + ivpi.clip(lower=0))

    umbral     = 1 + (OCDE_UMBRAL_ACUM * años)
    ratio_acum = (pat_act / pat_ini.fillna(pat_act)).fillna(1)

    result = pd.Series(np.where(
        ratio_acum > umbral * 2,        35,
        np.where(ratio_acum > umbral * 1.5, 20,
        np.where(ratio_acum > umbral,       10, 0))
    ).astype(float), index=df.index)
    log.info(f"d4_evolucion: ratio medio={ratio_acum.mean():.2f}, alertas={(ratio_acum > umbral).sum()}")
    return result


# ── Score compuesto ───────────────────────────────────────────────────────

def score_internacional(df: pd.DataFrame) -> pd.DataFrame:
    total = pd.Series(0.0, index=df.index)
    peso_disponible = 0
    for col, peso in PESOS.items():
        if col in df.columns:
            col_scores = df[col].clip(0, MAXIMOS[col])
            # Solo contar el peso si el indicador tiene datos reales (no todos cero)
            if col_scores.max() > 0:
                peso_disponible += peso
            total += (col_scores / MAXIMOS[col]) * peso
    # Renormalizar a 100 basado en pesos con datos reales
    if peso_disponible > 0 and peso_disponible < 100:
        total = (total / peso_disponible * 100)
        log.info(f"Renormalizando score: peso_disponible={peso_disponible}/100")
    df["score_internacional"] = total.round(1).clip(0, 100)
    df["nivel_internacional"] = df["score_internacional"].apply(
        lambda s: "CRÍTICO" if s >= 70 else "ALTO" if s >= 45 else "MEDIO" if s >= 20 else "BAJO"
    )
    return df


def scores_por_marco(df: pd.DataFrame) -> pd.DataFrame:
    grupos = {
        "score_fatf": ["A1_pep", "A2_beneficial_ow", "A3_cash_ratio", "A4_jurisdiccion"],
        "score_wb":   ["B1_pares_lac", "B2_brecha_sal"],
        "score_ti":   ["C1_velocidad", "C2_sector"],
        "score_ocde": ["D1_completitud", "D2_conflicto", "D3_puerta", "D4_evolucion"],
    }
    for nombre, cols in grupos.items():
        presentes = [c for c in cols if c in df.columns]
        df[nombre] = df[presentes].sum(axis=1).clip(0, 100).round(1) if presentes else 0.0
    return df


# ── Punto de entrada ──────────────────────────────────────────────────────

def run_indicadores() -> pd.DataFrame:
    log.info("=" * 60)
    log.info("INDICADORES INTERNACIONALES — FATF | WB | TI | OCDE")
    log.info("=" * 60)

    # Usar scoring_riesgo.csv como base directa — ya tiene pn_actual, ingresos, ivpi deflactados
    # NO mergear con ddjj_normalizada (tiene años anteriores → duplicados)
    s3 = _cargar("scoring_riesgo.csv")

    if s3.empty:
        log.error("Sin scoring_riesgo.csv. Corré fases 1-3 primero.")
        return pd.DataFrame()

    df = s3.copy()
    log.info(f"Base: {len(df)} registros únicos (scoring 2024), cols clave: pn_actual={('pn_actual' in df.columns)}, ivpi={('ivpi' in df.columns)}, ingresos={('ingresos' in df.columns)}")

    # Calcular 12 indicadores
    log.info("Calculando FATF...")
    df["A1_pep"]           = a1_pep(df)
    df["A2_beneficial_ow"] = a2_beneficial_ow(df)
    df["A3_cash_ratio"]    = a3_cash_ratio(df)
    df["A4_jurisdiccion"]  = a4_jurisdiccion(df)

    log.info("Calculando World Bank...")
    df["B1_pares_lac"]  = b1_pares_lac(df)
    df["B2_brecha_sal"] = b2_brecha_salario(df)

    log.info("Calculando TI...")
    df["C1_velocidad"] = c1_velocidad(df)
    df["C2_sector"]    = c2_sector(df)

    log.info("Calculando OCDE...")
    df["D1_completitud"] = d1_completitud(df)
    df["D2_conflicto"]   = d2_conflicto(df)
    df["D3_puerta"]      = d3_puerta_giratoria(df)
    df["D4_evolucion"]   = d4_evolucion_ocde(df)

    df = score_internacional(df)
    df = scores_por_marco(df)

    # Banderas por indicador
    for col in PESOS:
        if col in df.columns:
            df[col + "_bandera"] = df[col].apply(_bandera)

    # Columnas de salida
    cols_id    = [c for c in ["cuit", "cuil", "cuil_declarante", "funcionario_apellido_nombre",
                               "apellido_nombre", "nombre", "organismo", "cargo", "poder", "anio"] if c in df.columns]
    cols_f3    = [c for c in ["ivpi", "ivpi_bandera", "score_riesgo", "nivel_riesgo",
                               "pn_actual", "pn_ant", "ingresos", "delta_pn"] if c in df.columns]
    cols_ind   = list(PESOS.keys())
    cols_marco = ["score_fatf", "score_wb", "score_ti", "score_ocde"]
    cols_final = ["score_internacional", "nivel_internacional"]

    todas = cols_id + cols_f3 + cols_ind + [c + "_bandera" for c in PESOS] + cols_marco + cols_final
    salida = df[[c for c in todas if c in df.columns]].copy()
    salida.sort_values("score_internacional", ascending=False, inplace=True)

    salida.to_csv(PROC_DIR / "indicadores_internacionales.csv", index=False)
    log.info(f"→ indicadores_internacionales.csv ({len(salida)} registros)")

    # Perfil completo (merge con scoring para tener todo)
    if not s3.empty:
        c_s = _col(salida, ["cuit", "cuil", "cuil_declarante"])
        c_p = _col(s3,     ["cuit", "cuil", "cuil_declarante"])
        if c_s and c_p:
            perfil = salida.merge(
                s3[[c for c in s3.columns if c not in salida.columns or c == c_p]],
                left_on=c_s, right_on=c_p, how="left", suffixes=("", "_s3")
            )
            perfil.to_csv(PROC_DIR / "perfil_riesgo_completo.csv", index=False)
            log.info(f"→ perfil_riesgo_completo.csv ({len(perfil)} registros)")

    # Resumen
    log.info("-" * 40)
    for nivel in ["CRÍTICO", "ALTO", "MEDIO", "BAJO"]:
        n   = (salida["nivel_internacional"] == nivel).sum()
        pct = n / len(salida) * 100 if len(salida) else 0
        log.info(f"  {nivel:10s}: {n:6d} ({pct:.1f}%)")

    return salida


def resumen_json(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    return {
        "total_funcionarios":   len(df),
        "distribucion":         df["nivel_internacional"].value_counts().to_dict() if "nivel_internacional" in df.columns else {},
        "promedio_por_marco":   {m: round(float(df[m].mean()), 1) for m in ["score_fatf","score_wb","score_ti","score_ocde"] if m in df.columns},
        "alertas_rojas_por_indicador": {
            col: int((df[col + "_bandera"] == "ROJA").sum())
            for col in PESOS if col + "_bandera" in df.columns
            and (df[col + "_bandera"] == "ROJA").sum() > 0
        },
        "contexto": {
            "ar_cpi_ti_2023":      TI_AR_CPI,
            "ar_wb_cci_percentil": WB_AR_PERCENTIL,
            "lac_wb_cci_promedio": WB_LAC_PERCENTIL,
            "ocde_umbral_acum":    f"{OCDE_UMBRAL_ACUM}× ingreso/año",
            "fatf_cash_umbral":    f"{int(FATF_CASH_UMBRAL*100)}% del patrimonio",
            "ti_velocidad_bm":     f"{TI_VELOCIDAD_BM}× ingreso/año (CPI<40)",
            "fuentes": {
                "FATF": "https://www.fatf-gafi.org/en/topics/high-risk-jurisdictions.html",
                "WB":   "https://info.worldbank.org/governance/wgi/",
                "TI":   "https://www.transparency.org/en/cpi/2023",
                "OCDE": "https://www.oecd.org/gov/ethics/recommendation-public-integrity/",
            },
        },
    }


if __name__ == "__main__":
    resultado = run_indicadores()
    if not resultado.empty:
        print(json.dumps(resumen_json(resultado), indent=2, ensure_ascii=False))