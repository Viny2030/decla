"""Red organismo ↔ sector privado, a partir de los pasos público-privado declarados.

Es agregada a propósito: no incluye personas ni empleadores. El campo `sociedad`
también trae nombres de particulares (trabajo independiente) y declarar una
actividad privada no es una infracción: lo publicable como red es el patrón.
"""
import pandas as pd

SENTIDOS = {"ENTRADA": "entrada", "SIMULTANEO": "simultaneo", "SALIDA": "salida"}


def armar_red(df: pd.DataFrame) -> dict:
    """Cuenta declaraciones por par organismo-sector y por sentido."""
    vacio = {
        "declaraciones": 0, "personas": 0,
        "por_sentido": {v: 0 for v in SENTIDOS.values()},
        "enlaces": [],
    }
    if df is None or df.empty:
        return vacio

    d = df[df["sentido"].isin(SENTIDOS)].copy()
    d["organismo"] = d["organismo"].fillna("").astype(str).str.strip()
    d["sector_privado"] = d["sector_privado"].fillna("").astype(str).str.strip()
    d = d[(d["organismo"] != "") & (d["sector_privado"] != "")]
    if d.empty:
        return vacio

    enlaces = []
    for (org, sector), g in d.groupby(["organismo", "sector_privado"]):
        cuenta = g["sentido"].value_counts()
        fila = {"organismo": org, "sector": sector}
        for clave, nombre in SENTIDOS.items():
            fila[nombre] = int(cuenta.get(clave, 0))
        enlaces.append(fila)
    enlaces.sort(key=lambda e: (-(e["entrada"] + e["simultaneo"] + e["salida"]), e["organismo"], e["sector"]))

    conteo = d["sentido"].value_counts()
    return {
        "declaraciones": int(len(d)),
        "personas": int(d["cuil_funcionario"].nunique()),
        "por_sentido": {v: int(conteo.get(k, 0)) for k, v in SENTIDOS.items()},
        "enlaces": enlaces,
    }
