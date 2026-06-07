"""
pipeline.py
━━━━━━━━━━━
Orquestador del Monitor DDJJ.
Corre las fases en orden o de forma selectiva.

Uso:
  python pipeline.py                  # todas las fases (1 2 3 4 + indicadores)
  python pipeline.py --fase 1         # solo ETL
  python pipeline.py --fase 1 2 3     # fases combinadas
  python pipeline.py --fase 5         # solo indicadores internacionales
  python pipeline.py --sin-indicadores
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PIPELINE] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


def run(fases: list[int], con_indicadores: bool = True):
    inicio = time.time()

    print("\n" + "═" * 60)
    print(f"  MONITOR DDJJ  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Fases: {fases}{'  + indicadores' if con_indicadores else ''}")
    print("═" * 60 + "\n")

    if 1 in fases:
        t = time.time()
        from scripts.fase1_etl import run_etl
        run_etl()
        log.info(f"Fase 1 OK ({time.time()-t:.1f}s)\n")

    if 2 in fases:
        t = time.time()
        from scripts.fase2_cruces import run_cruces
        run_cruces()
        log.info(f"Fase 2 OK ({time.time()-t:.1f}s)\n")

    if 3 in fases:
        t = time.time()
        from scripts.fase3_scoring import run_scoring
        run_scoring()
        log.info(f"Fase 3 OK ({time.time()-t:.1f}s)\n")

    if 4 in fases:
        t = time.time()
        from scripts.fase4_ml import run_ml
        run_ml()
        log.info(f"Fase 4 OK ({time.time()-t:.1f}s)\n")

    if con_indicadores or 5 in fases:
        t = time.time()
        from scripts.indicadores_internacionales import run_indicadores
        run_indicadores()
        log.info(f"Indicadores internacionales OK ({time.time()-t:.1f}s)\n")

    total = time.time() - inicio
    print("\n" + "═" * 60)
    print(f"  PIPELINE COMPLETADO EN {total:.1f}s")
    print("═" * 60)

    proc = BASE_DIR / "data" / "processed"
    salidas = sorted(list(proc.glob("*.csv")) + list(proc.glob("*.json")))
    if salidas:
        print("\nArchivos generados:")
        for f in salidas:
            print(f"  {f.name:<50}  {f.stat().st_size/1024:6.1f} KB")


def main():
    parser = argparse.ArgumentParser(description="Monitor DDJJ Pipeline")
    parser.add_argument(
        "--fase", nargs="*", type=int, choices=[1, 2, 3, 4, 5],
        help="Fases: 1=ETL 2=Cruces 3=Scoring 4=ML 5=Indicadores. Sin --fase corre todas."
    )
    parser.add_argument("--sin-indicadores", action="store_true",
                        help="Omitir cálculo de indicadores internacionales")
    args = parser.parse_args()

    fases = args.fase if args.fase else [1, 2, 3, 4]
    con_ind = not args.sin_indicadores and 5 not in fases
    # si eligió explícitamente --fase 5, se corre solo indicadores
    if args.fase and 5 in args.fase:
        con_ind = True

    run(fases, con_indicadores=con_ind)


if __name__ == "__main__":
    main()
