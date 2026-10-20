"""
scripts/tipo_cambio.py
━━━━━━━━━━━━━━━━━━━━━━
Única fuente del tipo de cambio para todo el Monitor DDJJ (ETL, scoring,
API y dashboard).

Criterio: dólar MINORISTA, promedio vendedor, del último día hábil de
diciembre del año declarado — API pública de estadísticas del BCRA v4.0,
variable 4 (Comunicación B 9791).

Hasta oct-2026 convivían tres valores para el 31/12/2024: $1060,28 (este, en
fase 1), $1045 (fijo en fase 3, la API y el frontend, que no coincide con
ninguna serie) y, para 2023, $808,45 rotulado "BNA" pero que es el mayorista
A3500. Ahora todos leen data/processed/tipo_cambio.csv, que escribe la fase 1.
"""

import logging
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TC_CSV   = BASE_DIR / "data" / "processed" / "tipo_cambio.csv"

BCRA_API = "https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/4?desde={desde}&hasta={hasta}"
FUENTE   = "BCRA v4.0 var. 4 — minorista promedio vendedor, último día hábil de diciembre"

# Respaldo si la API no responde: mismos valores de la API (consultados el 20/10/2026).
TC_RESPALDO = {2020: 89.87, 2021: 108.29, 2022: 184.64, 2023: 847.11, 2024: 1060.28, 2025: 1479.28}


def consultar_bcra(anio: int) -> dict | None:
    """{'anio', 'fecha', 'valor', 'fuente'} del último día hábil de diciembre, o None."""
    try:
        url = BCRA_API.format(desde=f"{anio}-12-01", hasta=f"{anio}-12-31")
        r = requests.get(url, timeout=30, headers={"User-Agent": "monitor-ddjj/1.0"})
        r.raise_for_status()
        res = r.json().get("results", [])
        detalle = res[0].get("detalle", []) if res else []
        if detalle:
            ult = max(detalle, key=lambda d: d["fecha"])
            return {"anio": anio, "fecha": ult["fecha"], "valor": round(float(ult["valor"]), 2), "fuente": FUENTE}
    except Exception as e:
        log.warning(f"BCRA no disponible para {anio}: {e}")
    return None


def actualizar_tabla(anios) -> pd.DataFrame:
    """Consulta el BCRA para cada año pedido y guarda tipo_cambio.csv
    (conserva los años ya guardados; si la API falla usa el respaldo)."""
    filas = {int(a): None for a in anios}
    previo = cargar_tabla()
    for anio in filas:
        fila = consultar_bcra(anio)
        if fila is None and anio in previo:
            fila = previo[anio]
        if fila is None and anio in TC_RESPALDO:
            fila = {"anio": anio, "fecha": f"{anio}-12-31", "valor": TC_RESPALDO[anio], "fuente": "respaldo: " + FUENTE}
            log.warning(f"Usando TC de respaldo {anio}: ${TC_RESPALDO[anio]:.2f}")
        filas[anio] = fila
    todas = {**previo, **{a: f for a, f in filas.items() if f}}
    df = pd.DataFrame(sorted(todas.values(), key=lambda f: f["anio"]))
    TC_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(TC_CSV, index=False)
    for f in df.itertuples():
        log.info(f"TC {f.anio} ({f.fecha}): ${f.valor:.2f}")
    return df


def cargar_tabla() -> dict[int, dict]:
    if not TC_CSV.exists():
        return {}
    try:
        df = pd.read_csv(TC_CSV)
        return {int(r["anio"]): r for r in df.to_dict("records")}
    except Exception:
        return {}


def tc_por_anio() -> dict[int, float]:
    """TC por año: lo guardado por la fase 1 y, para los años que falten, el respaldo."""
    tabla = {a: float(f["valor"]) for a, f in cargar_tabla().items()}
    return {**TC_RESPALDO, **tabla}
