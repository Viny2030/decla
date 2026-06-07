"""
scripts/fase2_cruces.py
━━━━━━━━━━━━━━━━━━━━━━━
Fase 2 — Motor de Cruce Relacional
  Cruce 1: CUIT sociedad DDJJ × adjudicaciones Comprar.gob.ar  → alerta ROJA
  Cruce 2: Nombramientos 2023-2024 × directorios BORA          → alerta AMARILLA

Salidas:
  data/processed/alertas_conflicto.csv
  data/processed/alertas_puertas_giratorias.csv
"""

import logging
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="[CRUCE] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"
RAW_DIR  = BASE_DIR / "data" / "raw"

COMPRAR_URL = (
    "https://contrataciones.economia.gob.ar/api/v2/licitaciones"
    "?estado=adjudicada&limit=1000&offset={offset}"
)


def _col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def _cargar(nombre: str) -> pd.DataFrame:
    p = PROC_DIR / nombre
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def descargar_adjudicaciones() -> pd.DataFrame:
    dest = RAW_DIR / "comprar_adjudicaciones.csv"
    if dest.exists():
        log.info("Comprar: caché local")
        return pd.read_csv(dest, low_memory=False)
    registros, offset = [], 0
    headers = {"User-Agent": "monitor-ddjj/1.0"}
    while True:
        try:
            r = requests.get(COMPRAR_URL.format(offset=offset), headers=headers, timeout=30)
            items = r.json().get("data", {}).get("licitaciones", [])
            if not items:
                break
            registros.extend(items)
            log.info(f"  Comprar: {len(registros)} adjudicaciones...")
            if len(items) < 1000:
                break
            offset += 1000
        except Exception as e:
            log.warning(f"  Error Comprar: {e}")
            break
    df = pd.json_normalize(registros) if registros else pd.DataFrame()
    if not df.empty:
        df.to_csv(dest, index=False)
    return df


def extraer_cuits_sociedades(ddjj: pd.DataFrame) -> pd.DataFrame:
    cols_soc = [c for c in ddjj.columns if any(
        k in c for k in ["cuit_soc", "sociedad", "participacion", "accion", "cuota"]
    )]
    cuil_col   = _col(ddjj, ["cuil", "cuil_declarante"])
    nombre_col = _col(ddjj, ["apellido_nombre", "nombre"])

    registros = []
    for _, row in ddjj.iterrows():
        for col in cols_soc:
            cuit = row.get(col)
            if pd.notna(cuit) and str(cuit).strip() not in ("", "nan"):
                registros.append({
                    "cuil_funcionario":   row.get(cuil_col, "") if cuil_col else "",
                    "nombre_funcionario": row.get(nombre_col, "") if nombre_col else "",
                    "cuit_sociedad":      str(cuit).strip(),
                })
    return pd.DataFrame(registros)


def cruce1_conflicto_interes(ddjj: pd.DataFrame, adjudicaciones: pd.DataFrame) -> pd.DataFrame:
    log.info("Cruce 1 — Conflicto de Interés...")
    sociedades = extraer_cuits_sociedades(ddjj)
    if sociedades.empty or adjudicaciones.empty:
        log.warning("Sin datos para Cruce 1")
        return pd.DataFrame()

    cuit_col_adj = _col(adjudicaciones, [
        c for c in adjudicaciones.columns if "cuit" in c.lower() or "proveedor" in c.lower()
    ] if not adjudicaciones.empty else [])

    if not cuit_col_adj:
        log.warning("Sin columna CUIT en adjudicaciones")
        return pd.DataFrame()

    adjudicaciones["cuit_norm"] = adjudicaciones[cuit_col_adj].astype(str).str.replace("-", "").str.strip()
    sociedades["cuit_norm"]     = sociedades["cuit_sociedad"].astype(str).str.replace("-", "").str.strip()

    alertas = sociedades.merge(adjudicaciones, on="cuit_norm", how="inner")
    alertas["tipo_alerta"] = "CONFLICTO_INTERES"
    alertas["criticidad"]  = "ROJA"
    alertas["descripcion"] = (
        "Funcionario con participación societaria en empresa adjudicada en Comprar.gob.ar."
    )
    alertas.to_csv(PROC_DIR / "alertas_conflicto.csv", index=False)
    log.info(f"  {len(alertas)} alertas de conflicto → alertas_conflicto.csv")
    return alertas


def cruce2_puertas_giratorias(ddjj: pd.DataFrame) -> pd.DataFrame:
    log.info("Cruce 2 — Puertas Giratorias...")
    if ddjj.empty:
        return pd.DataFrame()

    fecha_col = _col(ddjj, ["fecha_alta", "fecha_asuncion", "fecha_inicio"])
    if fecha_col:
        ddjj[fecha_col] = pd.to_datetime(ddjj[fecha_col], errors="coerce")
        recientes = ddjj[ddjj[fecha_col].dt.year.isin([2023, 2024])].copy()
    else:
        recientes = ddjj.copy()

    alertas = []
    for _, row in recientes.iterrows():
        cuits = extraer_cuits_sociedades(pd.DataFrame([row]))
        for _, soc in cuits.iterrows():
            alertas.append({
                "cuil_funcionario":   soc.get("cuil_funcionario", ""),
                "nombre_funcionario": soc.get("nombre_funcionario", ""),
                "cuit_sociedad":      soc.get("cuit_sociedad", ""),
                "tipo_alerta":        "PUERTA_GIRATORIA_POTENCIAL",
                "criticidad":         "AMARILLA",
                "descripcion":        "Funcionario 2023-2024 con participación societaria activa. Verificar en BORA.",
            })

    df_al = pd.DataFrame(alertas)
    df_al.to_csv(PROC_DIR / "alertas_puertas_giratorias.csv", index=False)
    log.info(f"  {len(df_al)} alertas puertas giratorias → alertas_puertas_giratorias.csv")
    return df_al


def run_cruces() -> dict:
    log.info("=" * 55)
    log.info("FASE 2 — CRUCES RELACIONALES")
    log.info("=" * 55)
    ddjj  = _cargar("ddjj_normalizada.csv")
    adjud = descargar_adjudicaciones()
    return {
        "conflicto":  cruce1_conflicto_interes(ddjj, adjud),
        "puertas":    cruce2_puertas_giratorias(ddjj),
    }


if __name__ == "__main__":
    r = run_cruces()
    print(f"Conflicto: {len(r['conflicto'])}  |  Puertas: {len(r['puertas'])}")
