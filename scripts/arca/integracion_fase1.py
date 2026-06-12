"""
integracion_fase1.py
Parche para incorporar ws_sr_constancia_inscripcion en fase1_etl.py.

Enriquece el DataFrame de funcionarios con datos de ARCA antes de los cruces.

Variables de entorno requeridas:
    ARCA_CERT   ruta a .crt  O  contenido PEM directo
    ARCA_KEY    ruta a .key  O  contenido PEM directo
    ARCA_PROD   "1" = producción  (opcional, default homologación)
"""

import os
import time
import logging
import pandas as pd

from scripts.arca import ConsultaConstancia

logger = logging.getLogger(__name__)


def enriquecer_con_arca(
    df: pd.DataFrame,
    col_cuit: str = "cuit",
    prod: bool = None,
    pausa_seg: float = 0.5,
) -> pd.DataFrame:
    """
    Agrega columnas de ARCA al DataFrame de funcionarios.

    Columnas añadidas:
        arca_nombre          Nombre o razón social según padrón
        arca_tipo_persona    FISICA / JURIDICA
        arca_estado_cuit     ACTIVO / INACTIVO / BLOQUEADO / ...
        arca_domicilio       Domicilio fiscal
        arca_actividad_ppal  Actividad principal (orden=1)
        arca_impuestos       Lista de impuestos inscriptos (string)
        arca_monotributo_cat Categoría de monotributo si aplica
        arca_error           Mensaje de error si la consulta falla

    Args:
        df:        DataFrame con columna CUIT
        col_cuit:  Nombre de la columna con el CUIT
        prod:      True = producción  (default: lee env ARCA_PROD)
        pausa_seg: Pausa entre consultas para no saturar el WS
    """
    if prod is None:
        prod = os.getenv("ARCA_PROD", "0") == "1"

    cliente    = ConsultaConstancia(prod=prod)
    resultados = []

    for cuit in df[col_cuit]:
        row = {
            "arca_nombre":          None,
            "arca_tipo_persona":    None,
            "arca_estado_cuit":     None,
            "arca_domicilio":       None,
            "arca_actividad_ppal":  None,
            "arca_impuestos":       None,
            "arca_monotributo_cat": None,
            "arca_error":           None,
        }
        try:
            cuit_limpio = int(str(cuit).replace("-", "").replace(".", ""))
            data = cliente.get_persona(cuit_limpio)

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
            row["arca_impuestos"] = str([
                f"{i.get('idImpuesto')} {i.get('descripcionImpuesto', '')}"
                for i in impuestos
            ])

            mono = data.get("datosMonotributo", {})
            if mono:
                row["arca_monotributo_cat"] = mono.get("categoriaMonotributo")

        except Exception as e:
            logger.warning(f"CUIT {cuit}: error ARCA → {e}")
            row["arca_error"] = str(e)

        resultados.append(row)
        time.sleep(pausa_seg)

    df_arca = pd.DataFrame(resultados, index=df.index)
    return pd.concat([df, df_arca], axis=1)


# ── Prueba local ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    logging.basicConfig(level=logging.INFO, format="[ARCA] %(message)s")

    df_funcionarios = pd.DataFrame({
        "nombre":    ["FUNCIONARIO A", "FUNCIONARIO B"],
        "cuit":      [20000000168, 27000000189],
        "organismo": ["MINISTERIO X", "SECRETARÍA Y"],
    })

    print("Enriqueciendo con ARCA (homologación)...")
    df_enriquecido = enriquecer_con_arca(df_funcionarios)

    print(df_enriquecido[[
        "cuit", "arca_nombre", "arca_estado_cuit",
        "arca_actividad_ppal", "arca_error"
    ]].to_string())

    out = "/tmp/funcionarios_arca.csv"
    df_enriquecido.to_csv(out, index=False)
    print(f"\nGuardado en {out}")