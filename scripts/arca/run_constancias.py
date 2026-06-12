"""
run_constancias.py
Consulta la constancia de inscripción ARCA para todos los funcionarios
en data/processed/sujetos_obligados_clean.csv y guarda el resultado
en data/processed/constancias_arca.csv

Columnas clave en la salida:
    cuit
    arca_nombre
    arca_estado_cuit        ACTIVO / INACTIVO / BLOQUEADO
    arca_tipo_persona       FISICA / JURIDICA
    arca_domicilio
    arca_actividad_ppal
    arca_impuestos
    arca_monotributo_cat
    arca_regimen_simplificado   True si está inscripto en Ganancias régimen simplificado
    arca_estado_monotributo     AC / NA / etc
    arca_error
    arca_fecha_consulta
"""

import os
import sys
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime

# Asegurar imports desde raíz del repo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.arca import ConsultaConstancia

logging.basicConfig(level=logging.INFO, format="[ARCA] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
PROC_DIR  = BASE_DIR / "data" / "processed"
INPUT_CSV = PROC_DIR / "sujetos_obligados_clean.csv"
OUT_CSV   = PROC_DIR / "constancias_arca.csv"

# Pausa entre consultas para no saturar el WS (segundos)
PAUSA = 0.5


def es_regimen_simplificado(data: dict) -> tuple[bool, str]:
    """
    Detecta si el contribuyente está inscripto en Ganancias régimen simplificado.
    Retorna (bool, estado_monotributo).
    """
    mono = data.get("datosMonotributo", {})
    if not mono:
        return False, ""

    impuesto = mono.get("impuesto", {})
    if isinstance(impuesto, list):
        impuesto = next((i for i in impuesto if str(i.get("idImpuesto")) == "20"), {})

    estado = impuesto.get("estadoImpuesto", "")
    return estado == "AC", estado


def procesar_resultado(data: dict) -> dict:
    """Extrae los campos relevantes de la respuesta get_persona."""
    row = {
        "arca_nombre":               None,
        "arca_tipo_persona":         None,
        "arca_estado_cuit":          None,
        "arca_domicilio":            None,
        "arca_actividad_ppal":       None,
        "arca_impuestos":            None,
        "arca_monotributo_cat":      None,
        "arca_regimen_simplificado": False,
        "arca_estado_monotributo":   None,
        "arca_error":                None,
        "arca_fecha_consulta":       datetime.now().strftime("%Y-%m-%d"),
    }

    # Wrapper getPersona_v2Response
    if "getPersona_v2Response" in data:
        data = data["getPersona_v2Response"].get("personaReturn", data)

    dg = data.get("datosGenerales", {})
    row["arca_nombre"]       = dg.get("nombre") or dg.get("razonSocial")
    row["arca_tipo_persona"] = dg.get("tipoPersona")
    row["arca_estado_cuit"]  = dg.get("estadoClave")

    domicilio = dg.get("domicilioFiscal", {})
    if domicilio:
        row["arca_domicilio"] = (
            f"{domicilio.get('direccion', '')} "
            f"{domicilio.get('localidad', '')} "
            f"{domicilio.get('descripcionProvincia', '')}"
        ).strip()

    rg          = data.get("datosRegimenGeneral", {})
    actividades = rg.get("actividad", [])
    if isinstance(actividades, dict):
        actividades = [actividades]
    ppal = next((a for a in actividades if a.get("orden") == "1"), None)
    if ppal:
        row["arca_actividad_ppal"] = ppal.get("descripcionActividad")

    impuestos = rg.get("impuesto", [])
    if isinstance(impuestos, dict):
        impuestos = [impuestos]
    row["arca_impuestos"] = "; ".join([
        f"{i.get('idImpuesto')} {i.get('descripcionImpuesto', '')}"
        for i in impuestos
    ])

    mono = data.get("datosMonotributo", {})
    if mono:
        cat = mono.get("categoriaMonotributo", {})
        if isinstance(cat, dict):
            row["arca_monotributo_cat"] = cat.get("descripcionCategoria")

    simplificado, estado_mono = es_regimen_simplificado(data)
    row["arca_regimen_simplificado"] = simplificado
    row["arca_estado_monotributo"]   = estado_mono

    return row


def main():
    if not INPUT_CSV.exists():
        log.error(f"No existe {INPUT_CSV} — corré primero la Fase 1 del pipeline")
        sys.exit(1)

    df = pd.read_csv(INPUT_CSV, low_memory=False)
    log.info(f"Funcionarios a consultar: {len(df)}")

    # Detectar columna CUIT
    col_cuit = next((c for c in df.columns if "cuit" in c.lower() or "cuil" in c.lower()), None)
    if not col_cuit:
        log.error("No se encontró columna CUIT/CUIL en el CSV")
        sys.exit(1)

    log.info(f"Columna CUIT: {col_cuit}")

    prod    = os.getenv("ARCA_PROD", "0") == "1"
    cliente = ConsultaConstancia(prod=prod)
    log.info(f"Entorno: {'PRODUCCIÓN' if prod else 'HOMOLOGACIÓN'}")

    resultados = []
    errores    = 0

    for i, cuit in enumerate(df[col_cuit], 1):
        try:
            cuit_limpio = int(str(cuit).replace("-", "").replace(".", ""))
            data        = cliente.get_persona(cuit_limpio)
            row         = procesar_resultado(data)
            row["cuit"] = cuit
            log.info(f"[{i}/{len(df)}] {cuit} → {row['arca_nombre']} ({row['arca_estado_cuit']}) regimen_simplificado={row['arca_regimen_simplificado']}")
        except Exception as e:
            log.warning(f"[{i}/{len(df)}] {cuit} → ERROR: {e}")
            row = {
                "cuit":                      cuit,
                "arca_nombre":               None,
                "arca_tipo_persona":         None,
                "arca_estado_cuit":          None,
                "arca_domicilio":            None,
                "arca_actividad_ppal":       None,
                "arca_impuestos":            None,
                "arca_monotributo_cat":      None,
                "arca_regimen_simplificado": None,
                "arca_estado_monotributo":   None,
                "arca_error":                str(e),
                "arca_fecha_consulta":       datetime.now().strftime("%Y-%m-%d"),
            }
            errores += 1

        resultados.append(row)

        import time
        time.sleep(PAUSA)

    df_out = pd.DataFrame(resultados)
    df_out.to_csv(OUT_CSV, index=False)

    log.info(f"\n{'='*50}")
    log.info(f"Total consultados: {len(df)}")
    log.info(f"Errores:           {errores}")
    log.info(f"Con régimen simplificado: {df_out['arca_regimen_simplificado'].sum()}")
    log.info(f"Guardado en: {OUT_CSV}")


if __name__ == "__main__":
    main()