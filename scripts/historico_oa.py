"""
scripts/historico_oa.py
━━━━━━━━━━━━━━━━━━━━━━━
Histórico de DDJJ de años anteriores para /api/historico/{cuit}
(evolución patrimonial en la ficha del funcionario).

La OA publica los años anteriores dentro de zips de ~130 MB
(declaraciones-juradas-2023.zip trae 2012-2023). Como esos cortes ya no
cambian, se generan una vez y se suben al repo en versión reducida:

    data/processed/ddjj_2022_norm.csv
    data/processed/ddjj_2023_norm.csv

Una fila por persona y año: la DDJJ Anual si existe (si no, Inicial o Baja),
y dentro de ésa la última rectificativa. Montos en formato OA crudo (la API
los convierte con utils_oa.parsear_oa).

Uso:  python scripts/historico_oa.py            # genera los que falten
      python scripts/historico_oa.py --forzar   # regenera
"""

import io
import logging
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.fase1_etl import quitar_copias_corruptas, _recursos_ckan, DDJJ_PKG  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[HIST] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"
RAW_DIR  = BASE_DIR / "data" / "raw"
ANIOS    = (2022, 2023)

COLUMNAS = ["dj_id", "cuit", "anio", "tipo_declaracion_jurada_id", "tipo_declaracion_jurada_descripcion",
            "rectificativa", "funcionario_apellido_nombre", "organismo", "cargo",
            "total_bienes_inicio", "deudas_inicio", "total_bienes_final", "total_deudas_final",
            "total_ingreso_neto_c1234", "ingresos_neto_gastos", "ingresos_trabajos_alquileres_rentas"]


def _zip_mas_reciente(urls: list[str], anio: int) -> str | None:
    """El zip anual más nuevo que puede contener el año (el de 2023 trae 2012-2023)."""
    cands = []
    for u in urls:
        m = re.search(r"declaraciones-juradas-(\d{4})\.zip$", u)
        if m and int(m.group(1)) >= anio:
            cands.append((int(m.group(1)), u))
    return max(cands)[1] if cands else None


def _abrir_zip(url: str) -> zipfile.ZipFile:
    dest = RAW_DIR / url.rsplit("/", 1)[-1]
    if not dest.exists():
        log.info(f"Descargando {dest.name}...")
        r = requests.get(url, headers={"User-Agent": "monitor-ddjj/1.0"}, timeout=600)
        r.raise_for_status()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
    return zipfile.ZipFile(dest)


def una_por_persona(df: pd.DataFrame) -> pd.DataFrame:
    tipo = df["tipo_declaracion_jurada_descripcion"].astype(str).str.strip().str.lower()
    df = df.assign(_pref=tipo.eq("anual").astype(int),
                   _rect=pd.to_numeric(df["rectificativa"], errors="coerce").fillna(0),
                   _id=pd.to_numeric(df["dj_id"], errors="coerce").fillna(0))
    return (df.sort_values(["cuit", "_pref", "_rect", "_id"], kind="mergesort")
              .drop_duplicates("cuit", keep="last")
              .drop(columns=["_pref", "_rect", "_id"])
              .reset_index(drop=True))


def generar(anios=ANIOS, forzar: bool = False) -> None:
    pendientes = [a for a in anios if forzar or not (PROC_DIR / f"ddjj_{a}_norm.csv").exists()]
    if not pendientes:
        log.info("Histórico ya generado")
        return
    urls = _recursos_ckan(DDJJ_PKG)
    for anio in pendientes:
        url = _zip_mas_reciente(urls, anio)
        if not url:
            log.warning(f"No hay zip de la OA que contenga {anio}")
            continue
        z = _abrir_zip(url)
        nombre = next((n for n in z.namelist()
                       if re.fullmatch(rf"declaraciones-juradas-{anio}-consolidado-al-\d{{8}}\.csv", n)), None)
        if not nombre:
            log.warning(f"{url.rsplit('/', 1)[-1]} no trae el consolidado {anio}")
            continue
        df = pd.read_csv(io.BytesIO(z.read(nombre)), dtype=str, low_memory=False)
        df = quitar_copias_corruptas(df)
        df = df[pd.to_numeric(df["anio"], errors="coerce") == anio]
        df["cuit"] = df["cuit"].astype(str).str.replace(r"\D", "", regex=True)
        df = df[df["cuit"].str.len() == 11]
        df = una_por_persona(df.reindex(columns=COLUMNAS))
        PROC_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(PROC_DIR / f"ddjj_{anio}_norm.csv", index=False)
        log.info(f"ddjj_{anio}_norm.csv — {len(df)} personas ({nombre})")


if __name__ == "__main__":
    generar(forzar="--forzar" in sys.argv)
