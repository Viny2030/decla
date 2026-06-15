"""
regimen_simplificado.py
Clasifica a cada funcionario según su elegibilidad al Régimen Simplificado
de Ganancias (Ley 27.799 — "Inocencia Fiscal", RG 5820/2026).

Lee:
    data/processed/scoring_riesgo.csv

Genera:
    data/processed/elegibilidad_regimen_simplificado.csv

Columnas de salida:
    cuit
    funcionario_apellido_nombre
    ingresos_max          (máximo no-nulo de 'ingresos' entre filas duplicadas del CUIT)
    pn_actual_max         (máximo no-nulo de 'pn_actual' entre filas duplicadas del CUIT)
    cumple_topes_economicos        SI / NO / SIN_DATOS
    es_gran_contribuyente_nacional SI / NO / SIN_DATOS  (placeholder — falta padrón GCN)
    elegible_regimen_simplificado  SI / NO / SIN_DATOS

Topes vigentes (RG 5820/2026):
    - Ingresos totales anuales:  <= $1.000.000.000
    - Patrimonio total:          <  $10.000.000.000
    - No ser Gran Contribuyente Nacional (GCN)

Nota: "elegible" != "adherido". La adhesión es voluntaria y se verifica
en ARCA con la caracterización 618 (Ganancias PH Simplificada), que no
está disponible en este pipeline todavía.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="[REGIMEN-SIMPLIFICADO] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent
PROC_DIR  = BASE_DIR / "data" / "processed"
INPUT_CSV = PROC_DIR / "scoring_riesgo.csv"
OUT_CSV   = PROC_DIR / "elegibilidad_regimen_simplificado.csv"

TOPE_INGRESOS   = 1_000_000_000   # $1.000 millones anuales
TOPE_PATRIMONIO = 10_000_000_000  # $10.000 millones


def _max_no_nulo(serie: pd.Series):
    """Máximo ignorando NaN. Si todo es NaN, devuelve NaN."""
    if serie.notna().any():
        return serie.max()
    return np.nan


def clasificar_topes(ingresos, pn_actual) -> str:
    """SI / NO / SIN_DATOS según los topes económicos."""
    ing_nan = pd.isna(ingresos)
    pn_nan  = pd.isna(pn_actual)

    # Si alguno de los dos datos disponibles ya supera el tope -> NO
    if not ing_nan and ingresos > TOPE_INGRESOS:
        return "NO"
    if not pn_nan and pn_actual >= TOPE_PATRIMONIO:
        return "NO"

    # Si faltan ambos datos -> no podemos afirmar nada
    if ing_nan and pn_nan:
        return "SIN_DATOS"

    # Si falta uno de los dos, pero el otro no descarta -> sigue sin certeza total
    if ing_nan or pn_nan:
        return "SIN_DATOS"

    # Ambos datos presentes y dentro de los topes
    return "SI"


def clasificar_elegibilidad(cumple_topes: str, es_gcn: str) -> str:
    """Combina topes económicos + condición de Gran Contribuyente Nacional."""
    if cumple_topes == "NO":
        return "NO"
    if es_gcn == "SI":
        return "NO"
    if cumple_topes == "SI" and es_gcn == "NO":
        return "SI"
    return "SIN_DATOS"


def main():
    if not INPUT_CSV.exists():
        log.error(f"No existe {INPUT_CSV} — corré primero la Fase 3 del pipeline")
        return 1

    df = pd.read_csv(INPUT_CSV, low_memory=False)
    log.info(f"Filas leídas de scoring_riesgo.csv: {len(df)}")

    # Deduplicar por CUIT: tomar el máximo no-nulo de ingresos y pn_actual
    agg = (
        df.groupby("cuit", as_index=False)
          .agg(
              funcionario_apellido_nombre=("funcionario_apellido_nombre", "first"),
              ingresos_max=("ingresos", _max_no_nulo),
              pn_actual_max=("pn_actual", _max_no_nulo),
          )
    )
    log.info(f"CUITs únicos: {len(agg)}")

    # Placeholder: todavía no tenemos el padrón de Grandes Contribuyentes Nacionales
    agg["es_gran_contribuyente_nacional"] = "SIN_DATOS"

    agg["cumple_topes_economicos"] = agg.apply(
        lambda r: clasificar_topes(r["ingresos_max"], r["pn_actual_max"]), axis=1
    )

    agg["elegible_regimen_simplificado"] = agg.apply(
        lambda r: clasificar_elegibilidad(
            r["cumple_topes_economicos"], r["es_gran_contribuyente_nacional"]
        ),
        axis=1,
    )

    resumen = agg["elegible_regimen_simplificado"].value_counts()
    log.info(f"\n{'='*50}")
    log.info("Resumen elegible_regimen_simplificado:")
    for k, v in resumen.items():
        log.info(f"  {k:10s}: {v}")

    agg.to_csv(OUT_CSV, index=False)
    log.info(f"Guardado en: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())