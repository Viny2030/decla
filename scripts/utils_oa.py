"""
scripts/utils_oa.py
━━━━━━━━━━━━━━━━━━━━
Utilidades compartidas para parsear el formato numérico "OA"
(Oficina Anticorrupción / datos.jus.gob.ar), donde los montos
vienen como string "11401021-93" en lugar de 11401021.93.

Usado por:
  - api/main.py            (parsear_oa, escalar — fila por fila)
  - scripts/fase1_etl.py    (parsear_oa_serie, vectorizado — columna completa)
  - scripts/fase3_scoring.py (parsear_oa_serie, como fallback defensivo)
"""

import re

import pandas as pd

# Match: dígitos (con posibles separadores , o .) + guión + dígitos al final
# Ej: "11401021-93" / "1.234.567-89" / "-500-25"
OA_PATTERN = re.compile(r'^-?\d[\d.,]*-\d+$')


def parsear_oa(v):
    """
    Parsea un valor escalar en formato OA: '11851166833-39' → 11851166833.39

    Devuelve None si:
      - v es None / NaN
      - v es un placeholder vacío ('---', '--', '-', 'None', 'nan')
      - no se puede convertir de ninguna forma
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s or s in ('---', '--', '-', 'None', 'nan'):
        return None
    try:
        # Ya es número
        return float(s)
    except ValueError:
        pass
    # Formato OA: dígitos-dígitos
    if '-' in s:
        partes = s.rsplit('-', 1)
        entero = partes[0].replace('-', '').replace(',', '')
        decimal = partes[1] if len(partes) > 1 else '0'
        try:
            return float(f"{entero}.{decimal}")
        except ValueError:
            return None
    return None


def parsear_oa_serie(serie: pd.Series) -> pd.Series:
    """
    Versión vectorizada de parsear_oa(), para columnas completas de un DataFrame.

    - Valores ya numéricos (o numéricos como string, ej. "1234.56") quedan igual.
    - Valores en formato OA ("11401021-93") se convierten a 11401021.93.
    - Placeholders ('---', '', 'nan', etc.) y valores no parseables quedan en NaN.

    No modifica la Serie original — devuelve una nueva Serie numérica (float).
    """
    s = serie.astype(str).str.strip()

    # Intento directo: si ya es numérico (incluye negativos normales, "1234.56", etc.)
    numerico = pd.to_numeric(s, errors="coerce")

    # Para lo que no parseó directo, probar el patrón OA "digitos-digitos"
    mask_oa = numerico.isna() & s.str.match(OA_PATTERN, na=False)
    if mask_oa.any():
        partes  = s[mask_oa].str.rsplit('-', n=1, expand=True)
        entero  = partes[0].str.replace('-', '', regex=False).str.replace(',', '', regex=False)
        decimal = partes[1]
        numerico.loc[mask_oa] = pd.to_numeric(entero + '.' + decimal, errors="coerce")

    return numerico