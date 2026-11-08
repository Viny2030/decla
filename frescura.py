"""
frescura.py — ficha de frescura de los datos (formato común del ecosistema)
===========================================================================
Cada sitio expone GET /api/frescura con la lista de sus datos y, para cada
uno, dos relojes distintos:

* técnico  — ultima_carga: cuándo el proceso automático cargó el dato por
  última vez. Si supera max_dias_carga, falló el código o la fuente no
  respondió: hay que revisar el pipeline.
* contenido — periodo_fin: hasta qué fecha llega el dato. Si supera
  max_dias_periodo, la fuente oficial no publicó nada nuevo (por ejemplo,
  el último recibo de dieta es de enero): hay que buscar el dato, no
  arreglar código.

La alarma central (repo mapa_compliance_portal, workflow frescura.yml) lee
este endpoint en todos los sitios y separa las dos alarmas.
"""

from __future__ import annotations

import re
from datetime import date, datetime

FORMATO = "frescura/1"
MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], start=1)}


def fecha_es(texto: str | None) -> date | None:
    """'04 Noviembre 2026' / '4 de noviembre de 2026' → date; 'Enero 2026' →
    último día del mes; '09/09/2026' → date. None si no hay fecha."""
    if not texto:
        return None
    t = texto.lower()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"(?:(\d{1,2})\s+(?:de\s+)?)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})", t)
    if m and m.group(2) in MESES:
        anio, mes = int(m.group(3)), MESES[m.group(2)]
        if m.group(1):
            return date(anio, mes, int(m.group(1)))
        sig = date(anio + (mes == 12), mes % 12 + 1, 1)
        return date.fromordinal(sig.toordinal() - 1)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _a_fecha(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return datetime.fromisoformat(str(v)[:19]).date()
    except ValueError:
        return fecha_es(str(v))


def evaluar(sitio: str, items: list[dict], hoy: date | None = None) -> dict:
    """Completa cada ítem con dias_desde_carga, dias_desde_periodo y estado:
    'atrasado_tecnico', 'atrasado_contenido' o 'al_dia'."""
    hoy = hoy or date.today()
    salida, resumen = [], {"al_dia": 0, "atrasado_tecnico": 0, "atrasado_contenido": 0}
    for it in items:
        it = dict(it)
        carga, fin = _a_fecha(it.get("ultima_carga")), _a_fecha(it.get("periodo_fin"))
        it["dias_desde_carga"] = (hoy - carga).days if carga else None
        it["dias_desde_periodo"] = (hoy - fin).days if fin else None
        if it.get("periodo_fin") and fin:
            it["periodo_fin"] = fin.isoformat()
        max_c, max_p = it.get("max_dias_carga"), it.get("max_dias_periodo")
        if max_c is not None and (carga is None or it["dias_desde_carga"] > max_c):
            it["estado"] = "atrasado_tecnico"
        elif max_p is not None and (fin is None or it["dias_desde_periodo"] > max_p):
            it["estado"] = "atrasado_contenido"
        else:
            it["estado"] = "al_dia"
        resumen[it["estado"]] += 1
        salida.append(it)
    return {"formato": FORMATO, "sitio": sitio, "generado": datetime.now().isoformat(timespec="seconds"),
            "resumen": resumen, "datos": salida}
