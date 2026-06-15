"""
run_constancias.py
Consulta el Padrón A13 de ARCA para los funcionarios en
data/processed/sujetos_obligados_clean.csv y guarda el resultado
en data/processed/constancias_arca.csv

Dedup + exclusión (evita reconsultar todo en cada corrida):
  - CUITs nuevos (no en constancias_arca.csv): siempre se consultan.
  - CUITs en cache SIN error: se reconsultan solo si pasaron
    >= REFRESH_DIAS días desde arca_fecha_consulta.
  - CUITs en cache CON error: se reintentan hasta MAX_INTENTOS_ERROR
    veces (contador acumulado en arca_intentos_error); luego se excluyen.

Columnas clave en la salida:
    cuit
    arca_nombre
    arca_apellido
    arca_razon_social
    arca_estado_cuit        ACTIVO / INACTIVO
    arca_tipo_persona       FISICA / JURIDICA
    arca_actividad_ppal
    arca_domicilio_fiscal
    arca_provincia
    arca_fecha_nacimiento
    arca_error
    arca_intentos_error     contador de errores consecutivos
    arca_fecha_consulta
"""

import os
import sys
import time
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.arca.padron_a13 import PadronA13

logging.basicConfig(level=logging.INFO, format="[ARCA] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
PROC_DIR  = BASE_DIR / "data" / "processed"
INPUT_CSV = PROC_DIR / "sujetos_obligados_clean.csv"
OUT_CSV   = PROC_DIR / "constancias_arca.csv"

PAUSA = 0.3  # segundos entre consultas

REFRESH_DIAS       = 15  # re-consultar CUITs OK después de N días
MAX_INTENTOS_ERROR = 3   # reintentar CUITs con error hasta N veces, luego excluir


def _norm_cuit(v) -> str:
    """Normaliza CUIT a string de solo dígitos (sin guiones, sin '.0')."""
    if pd.isna(v):
        return ""
    s = str(v).strip().replace("-", "")
    if s.endswith(".0"):
        s = s[:-2]
    return s


def procesar_resultado(data: dict, cuit_original: str) -> dict:
    """Extrae campos relevantes de la respuesta get_persona del A13."""
    row = {
        "cuit":                 cuit_original,
        "arca_nombre":          data.get("nombre"),
        "arca_apellido":        data.get("apellido"),
        "arca_razon_social":    data.get("razonSocial"),
        "arca_estado_cuit":     data.get("estadoClave"),
        "arca_tipo_persona":    data.get("tipoPersona"),
        "arca_actividad_ppal":  data.get("descripcionActividadPrincipal"),
        "arca_fecha_nacimiento":data.get("fechaNacimiento", "")[:10] if data.get("fechaNacimiento") else None,
        "arca_domicilio_fiscal": None,
        "arca_provincia":       None,
        "arca_error":           None,
        "arca_intentos_error":  0,
        "arca_fecha_consulta":  datetime.now().strftime("%Y-%m-%d"),
    }

    # Domicilio fiscal
    domicilios = data.get("domicilio", [])
    if isinstance(domicilios, dict):
        domicilios = [domicilios]
    fiscal = next((d for d in domicilios if d.get("tipoDomicilio") == "FISCAL"), None)
    if fiscal:
        row["arca_domicilio_fiscal"] = fiscal.get("direccion")
        row["arca_provincia"]        = fiscal.get("descripcionProvincia")

    return row


def cargar_padron(input_csv: Path) -> list[tuple[str, str]]:
    """
    Lee sujetos_obligados_clean.csv y devuelve una lista de pares
    (cuit_original, cuit_norm), deduplicada por cuit_norm (se queda
    con el primer formato de 'cuit_original' encontrado).
    """
    df = pd.read_csv(input_csv, low_memory=False)
    log.info(f"Filas en {input_csv.name}: {len(df)}")

    col_cuit = next((c for c in df.columns if "cuit" in c.lower() or "cuil" in c.lower()), None)
    if not col_cuit:
        log.error("No se encontró columna CUIT/CUIL en el CSV")
        sys.exit(1)
    log.info(f"Columna CUIT: {col_cuit}")

    vistos: dict[str, str] = {}
    for original in df[col_cuit]:
        norm = _norm_cuit(original)
        if norm and norm not in vistos:
            vistos[norm] = str(original)

    pares = list(vistos.items())  # [(cuit_norm, cuit_original), ...]
    log.info(f"CUITs únicos en padrón: {len(pares)}")
    return [(orig, norm) for norm, orig in pares]


def cargar_cache(out_csv: Path) -> pd.DataFrame:
    if not out_csv.exists():
        return pd.DataFrame()
    cache = pd.read_csv(out_csv, low_memory=False, dtype={"cuit": str})
    if cache.empty:
        return cache
    cache["_cuit_norm"] = cache["cuit"].apply(_norm_cuit)
    if "arca_intentos_error" not in cache.columns:
        cache["arca_intentos_error"] = 0
    cache["arca_intentos_error"] = pd.to_numeric(
        cache["arca_intentos_error"], errors="coerce"
    ).fillna(0).astype(int)
    return cache


def clasificar(padron: list[tuple[str, str]], cache: pd.DataFrame) -> dict:
    """
    Clasifica cada (cuit_original, cuit_norm) del padrón en:
      'nuevos'           — no estaban en cache
      'refresh'          — en cache OK pero vencidos (>= REFRESH_DIAS)
      'retry_error'      — en cache con error y aún con reintentos disponibles
      'cache_vigente'    — en cache OK y dentro de la ventana de refresh (no tocar)
      'excluidos_error'  — en cache con error y reintentos agotados
    Devuelve dict con listas de (cuit_original, cuit_norm).
    """
    resultado = {
        "nuevos": [], "refresh": [], "retry_error": [],
        "cache_vigente": [], "excluidos_error": [],
    }

    if cache.empty:
        resultado["nuevos"] = padron
        return resultado

    cache_idx = cache.set_index("_cuit_norm")
    hoy = datetime.now()

    for original, norm in padron:
        if norm not in cache_idx.index:
            resultado["nuevos"].append((original, norm))
            continue

        fila = cache_idx.loc[norm]
        if isinstance(fila, pd.DataFrame):  # por si hay duplicados en el cache
            fila = fila.iloc[0]

        error = fila.get("arca_error")
        tiene_error = pd.notna(error) and str(error).strip() != ""

        if tiene_error:
            intentos = int(fila.get("arca_intentos_error", 0))
            if intentos < MAX_INTENTOS_ERROR:
                resultado["retry_error"].append((original, norm))
            else:
                resultado["excluidos_error"].append((original, norm))
            continue

        # Sin error: chequear frescura
        fecha_str = fila.get("arca_fecha_consulta")
        try:
            fecha = datetime.strptime(str(fecha_str), "%Y-%m-%d")
            vencido = (hoy - fecha) >= timedelta(days=REFRESH_DIAS)
        except (ValueError, TypeError):
            vencido = True  # fecha inválida/faltante -> re-consultar

        if vencido:
            resultado["refresh"].append((original, norm))
        else:
            resultado["cache_vigente"].append((original, norm))

    return resultado


def consultar(cliente: PadronA13, a_consultar: list[tuple[str, str]], cache: pd.DataFrame) -> pd.DataFrame:
    resultados = []
    errores = 0

    for i, (original, norm) in enumerate(a_consultar, 1):
        try:
            data = cliente.get_persona(int(norm))
            row  = procesar_resultado(data, original)
            log.info(f"[{i}/{len(a_consultar)}] {original} → {row['arca_nombre']} {row['arca_apellido']} ({row['arca_estado_cuit']})")
        except Exception as e:
            log.warning(f"[{i}/{len(a_consultar)}] {original} → ERROR: {e}")
            intentos_previos = 0
            if not cache.empty:
                prev = cache[cache["_cuit_norm"] == norm]
                if not prev.empty:
                    intentos_previos = int(prev.iloc[0].get("arca_intentos_error", 0))
            row = {
                "cuit":                  original,
                "arca_nombre":           None,
                "arca_apellido":         None,
                "arca_razon_social":     None,
                "arca_estado_cuit":      None,
                "arca_tipo_persona":     None,
                "arca_actividad_ppal":   None,
                "arca_fecha_nacimiento": None,
                "arca_domicilio_fiscal": None,
                "arca_provincia":        None,
                "arca_error":            str(e),
                "arca_intentos_error":   intentos_previos + 1,
                "arca_fecha_consulta":   datetime.now().strftime("%Y-%m-%d"),
            }
            errores += 1

        resultados.append(row)
        time.sleep(PAUSA)

    log.info(f"Errores en esta corrida: {errores}")
    return pd.DataFrame(resultados)


def main():
    if not INPUT_CSV.exists():
        log.error(f"No existe {INPUT_CSV} — corré primero la Fase 1 del pipeline")
        sys.exit(1)

    padron = cargar_padron(INPUT_CSV)
    cache  = cargar_cache(OUT_CSV)

    clasif = clasificar(padron, cache)

    log.info(f"\n{'='*50}")
    log.info(f"  Nuevos             : {len(clasif['nuevos'])}")
    log.info(f"  Refresh (>{REFRESH_DIAS}d)     : {len(clasif['refresh'])}")
    log.info(f"  Retry error        : {len(clasif['retry_error'])}")
    log.info(f"  Cache vigente (skip): {len(clasif['cache_vigente'])}")
    log.info(f"  Excluidos (error x{MAX_INTENTOS_ERROR}+): {len(clasif['excluidos_error'])}")
    log.info(f"{'='*50}")

    a_consultar = clasif["nuevos"] + clasif["refresh"] + clasif["retry_error"]

    if not a_consultar:
        log.info("Nada para consultar — constancias_arca.csv ya está al día.")
        return

    prod    = os.getenv("ARCA_PROD", "0") == "1"
    cliente = PadronA13(prod=prod)
    log.info(f"Entorno: {'PRODUCCIÓN' if prod else 'HOMOLOGACIÓN'}")
    log.info(f"A consultar esta corrida: {len(a_consultar)}")

    df_nuevos = consultar(cliente, a_consultar, cache)

    # Combinar con cache: descartar filas que se acaban de actualizar,
    # mantener el resto (incluye cache_vigente y excluidos_error tal cual)
    if not cache.empty:
        norms_actualizados = {norm for _, norm in a_consultar}
        cache_restante = cache[~cache["_cuit_norm"].isin(norms_actualizados)].drop(columns=["_cuit_norm"])
        df_out = pd.concat([cache_restante, df_nuevos], ignore_index=True)
    else:
        df_out = df_nuevos

    df_out.to_csv(OUT_CSV, index=False)

    log.info(f"\n{'='*50}")
    log.info(f"Total en {OUT_CSV.name}: {len(df_out)}")
    if "arca_estado_cuit" in df_out.columns:
        log.info(f"ACTIVOS: {(df_out['arca_estado_cuit'] == 'ACTIVO').sum()}")
    log.info(f"Guardado en: {OUT_CSV}")


if __name__ == "__main__":
    main()