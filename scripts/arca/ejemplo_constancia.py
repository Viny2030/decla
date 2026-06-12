"""
ejemplo_constancia.py
Prueba rápida del módulo de constancia de inscripción.
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.arca import ConsultaConstancia


def main():
    prod    = os.getenv("ARCA_PROD", "0") == "1"
    cliente = ConsultaConstancia(prod=prod)

    CUIT_PRUEBA = 20120344111
    print(f"\n── getPersona({CUIT_PRUEBA}) ──────────────────────")
    try:
        resultado = cliente.get_persona(CUIT_PRUEBA)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"  ERROR getPersona: {e}")

    CUIT_PRUEBA = 20000000168
    print(f"\n── getPersona({CUIT_PRUEBA}) ──────────────────────")
    try:
        resultado = cliente.get_persona(CUIT_PRUEBA)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"  ERROR getPersona: {e}")
        return

    dg = resultado.get("datosGenerales", {})
    print("\n── Resumen ──────────────────────────────────────")
    print(f"  Nombre:      {dg.get('nombre') or dg.get('razonSocial')}")
    print(f"  Tipo:        {dg.get('tipoPersona')}")
    print(f"  Estado CUIT: {dg.get('estadoClave')}")

    actividades = resultado.get("datosRegimenGeneral", {}).get("actividad", [])
    if isinstance(actividades, dict):
        actividades = [actividades]
    for act in actividades[:3]:
        print(f"  Actividad:   [{act.get('orden')}] {act.get('descripcionActividad')}")


if __name__ == "__main__":
    main()