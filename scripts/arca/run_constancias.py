"""
run_constancias.py
Consulta el Padrón A13 de ARCA para todos los funcionarios en
data/processed/sujetos_obligados_clean.csv y guarda el resultado
en data/processed/constancias_arca.csv

Columnas clave en la salida:
    cuit
    arca_nombre
    arca_apellido
    arca_estado_cuit        ACTIVO / INACTIVO
    arca_tipo_persona       FISICA / JURIDICA
    arca_domicilio_fiscal
    arca_provincia
    arca_actividad_ppal
    arca_fecha_nacimiento
    arca_error
    arca_fecha_consulta
"""

import os
import sys
import time
import logging
import pandas as pd
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.arca.padron_a13 import PadronA13

logging.basicConfig(level=logging.INFO, format="[ARCA] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent.parent
PROC_DIR  = BASE_DIR / "data" / "processed"
INPUT_CSV = PROC_DIR / "sujetos_obligados_clean.csv"
OUT_CSV   = PROC_DIR / "constancias_arca.csv"

PAUSA = 0.3  # segundos entre consultas


def procesar_resultado(data: dict, cuit) -> dict:
    """Extrae campos relevantes de la respuesta get_persona del A13."""
    row = {
        "cuit":                 cuit,
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


def main():
    if not INPUT_CSV.exists():
        log.error(f"No existe {INPUT_CSV} — corré primero la Fase 1 del pipeline")
        sys.exit(1)

    df = pd.read_csv(INPUT_CSV, low_memory=False)
    log.info(f"Funcionarios a consultar: {len(df)}")

    col_cuit = next((c for c in df.columns if "cuit" in c.lower() or "cuil" in c.lower()), None)
    if not col_cuit:
        log.error("No se encontró columna CUIT/CUIL en el CSV")
        sys.exit(1)

    log.info(f"Columna CUIT: {col_cuit}")

    prod    = os.getenv("ARCA_PROD", "0") == "1"
    cliente = PadronA13(prod=prod)
    log.info(f"Entorno: {'PRODUCCIÓN' if prod else 'HOMOLOGACIÓN'}")

    resultados = []
    errores    = 0

    for i, cuit in enumerate(df[col_cuit], 1):
        try:
            cuit_limpio = int(float(str(cuit).replace("-", "")))
            data        = cliente.get_persona(cuit_limpio)
            if i == 1:
                import json
                print("DEBUG data:", json.dumps(data, indent=2, ensure_ascii=False)[:500])
            row         = procesar_resultado(data, cuit)
            log.info(f"[{i}/{len(df)}] {cuit} → {row['arca_nombre']} {row['arca_apellido']} ({row['arca_estado_cuit']})")
        except Exception as e:
            log.warning(f"[{i}/{len(df)}] {cuit} → ERROR: {e}")
            row = {
                "cuit":                  cuit,
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
                "arca_fecha_consulta":   datetime.now().strftime("%Y-%m-%d"),
            }
            errores += 1

        resultados.append(row)
        time.sleep(PAUSA)

    df_out = pd.DataFrame(resultados)
    df_out.to_csv(OUT_CSV, index=False)

    log.info(f"\n{'='*50}")
    log.info(f"Total consultados:  {len(df)}")
    log.info(f"Errores:            {errores}")
    log.info(f"ACTIVOS:            {(df_out['arca_estado_cuit'] == 'ACTIVO').sum()}")
    log.info(f"Guardado en:        {OUT_CSV}")


if __name__ == "__main__":
    main()