"""
scripts/fase2_cruces.py
━━━━━━━━━━━━━━━━━━━━━━━
Fase 2 — Motor de Cruce Relacional
  Cruce 1: CUIT sociedad DDJJ × adjudicaciones Comprar.gob.ar  → alerta ROJA
  Cruce 1a: CUIT del funcionario × adjudicaciones del Boletín Oficial
            (Monitor Contratos, CONTRATOS_API_URL)                → alerta ROJA
  Cruce 1b: DDJJ "proveedor o contratista del Estado" = SI       → alerta AMARILLA
  Cruce 2: Actividades anteriores/posteriores (MAPPAP, OA): paso privado↔público
           en menos de 365 días o empleo privado simultáneo                → AMARILLA

Salidas:
  data/processed/alertas_conflicto.csv
  data/processed/alertas_puertas_giratorias.csv
"""

import io
import logging
import os
import re
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="[CRUCE] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"
RAW_DIR  = BASE_DIR / "data" / "raw"

# El endpoint anterior (contrataciones.economia.gob.ar/api/v2/licitaciones)
# dejó de existir (el dominio no resuelve): el cruce rojo daba siempre 0 y el
# error quedaba escondido en el log. Ahora se usan las adjudicaciones que el
# Monitor Contratos del ecosistema extrae del Boletín Oficial.
CONTRATOS_API_URL = os.getenv("CONTRATOS_API_URL", "https://contratos.ecosistematransparencia.com.ar").rstrip("/")
CONTRATOS_CSV = CONTRATOS_API_URL + "/api/contratos.csv"


def _col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def _cargar(nombre: str) -> pd.DataFrame:
    p = PROC_DIR / nombre
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def descargar_adjudicaciones() -> pd.DataFrame:
    """Adjudicaciones del Boletín Oficial (Monitor Contratos). Columnas clave:
    cuit_proveedor, proveedor_adjudicado, organismo_contratante,
    monto_adjudicado_bora, fecha, link_bora."""
    dest = RAW_DIR / "contratos_adjudicaciones.csv"
    try:
        r = requests.get(CONTRATOS_CSV, headers={"User-Agent": "monitor-ddjj/1.0"}, timeout=120)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), sep=";", dtype=str)
        df.to_csv(dest, index=False)
        con_cuit = df["cuit_proveedor"].map(_digitos).str.len().eq(11).sum() if "cuit_proveedor" in df.columns else 0
        log.info(f"  Contratos (BORA): {len(df)} adjudicaciones, {con_cuit} con CUIT — {CONTRATOS_API_URL}")
        return df
    except Exception as e:
        log.error(f"  Contratos no disponible ({CONTRATOS_CSV}): {e}")
        if dest.exists():
            log.warning("  Uso la última copia descargada")
            return pd.read_csv(dest, dtype=str)
        return pd.DataFrame()


_RE_CUIT = re.compile(r"^(20|23|24|27|30|33|34)\d{9}$")


def _cuit_valido(v) -> str | None:
    """Devuelve el CUIT normalizado (11 dígitos) o None.

    Antes se tomaba cualquier valor no vacío de columnas cuyo nombre contenía
    "cuota", "accion", "sociedad"... En el dataset de la OA esas columnas son
    MONTOS ("cuota_medico_asistencial", "aportes_sociedades_garantias_reciprocas",
    con valores "-00", "25200-00") y no hay CUIT de sociedades: se generaban
    132.750 "alertas" sin CUIL ni nombre de funcionario.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = re.sub(r"[^0-9]", "", str(v).split(".")[0] if isinstance(v, float) else str(v))
    return s if _RE_CUIT.match(s) else None


def extraer_cuits_sociedades(ddjj: pd.DataFrame) -> pd.DataFrame:
    cols_soc = [c for c in ddjj.columns if "cuit_soc" in c or c in ("cuit_sociedad", "sociedad_cuit")]
    cuil_col   = _col(ddjj, ["cuil", "cuil_declarante", "cuit"])
    nombre_col = _col(ddjj, ["funcionario_apellido_nombre", "apellido_nombre", "nombre"])
    vacio = pd.DataFrame(columns=["cuil_funcionario", "nombre_funcionario", "cuit_sociedad"])
    if not cols_soc or not cuil_col:
        log.warning("  La DDJJ publicada no trae CUIT de sociedades: no hay cruce societario posible")
        return vacio

    registros = []
    for _, row in ddjj.iterrows():
        cuil = _cuit_valido(row.get(cuil_col))
        if not cuil:
            continue
        for col in cols_soc:
            cuit = _cuit_valido(row.get(col))
            if cuit and cuit != cuil:
                registros.append({
                    "cuil_funcionario":   cuil,
                    "nombre_funcionario": row.get(nombre_col, "") if nombre_col else "",
                    "cuit_sociedad":      cuit,
                })
    return pd.DataFrame(registros).drop_duplicates() if registros else vacio


COLS_ALERTA = ["cuil_funcionario", "nombre_funcionario", "organismo", "cargo", "cuit_sociedad",
               "sociedad", "tipo_alerta", "criticidad", "descripcion"]

def _digitos(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return re.sub(r"[^0-9]", "", s)


def _base_personas(ddjj: pd.DataFrame) -> pd.DataFrame:
    d = ddjj.copy()
    d["cuil_funcionario"]   = d["cuit"].map(_digitos) if "cuit" in d.columns else ""
    d["nombre_funcionario"] = d.get("funcionario_apellido_nombre", "")
    return d[d["cuil_funcionario"].str.len() == 11]


def cruce1_conflicto_interes(ddjj: pd.DataFrame, adjudicaciones: pd.DataFrame) -> pd.DataFrame:
    """Dos fuentes:
    1. ROJA: CUIT de sociedad del funcionario adjudicada en Comprar (la DDJJ
       publicada no trae CUIT de sociedades, así que hoy no produce filas).
    2. AMARILLA: la DDJJ trae "proveedor_contratista" = SI. El dataset no
       documenta el campo: lo marcan tanto posibles proveedores como miembros de
       comisiones de compras/recepción. Se marca para verificar, nunca como ROJA."""
    log.info("Cruce 1 — Conflicto de Interés...")
    partes = []

    sociedades = extraer_cuits_sociedades(ddjj)
    if not sociedades.empty and not adjudicaciones.empty:
        cuit_col_adj = _col(adjudicaciones, ["cuit_proveedor"] + [
            c for c in adjudicaciones.columns if "cuit" in c.lower()])
        if cuit_col_adj:
            adjudicaciones["cuit_norm"] = adjudicaciones[cuit_col_adj].map(_digitos)
            sociedades["cuit_norm"]     = sociedades["cuit_sociedad"].map(_digitos)
            a = sociedades.merge(adjudicaciones, on="cuit_norm", how="inner")
            if not a.empty:
                a["tipo_alerta"] = "CONFLICTO_INTERES"
                a["criticidad"]  = "ROJA"
                a["descripcion"] = "Funcionario con participación societaria en empresa adjudicada en Comprar.gob.ar."
                partes.append(a)

    # 1a. El propio funcionario (persona física) figura como proveedor adjudicado
    if not adjudicaciones.empty and "cuit_proveedor" in adjudicaciones.columns and "cuit" in ddjj.columns:
        adj = adjudicaciones.assign(cuil_funcionario=adjudicaciones["cuit_proveedor"].map(_digitos))
        adj = adj[adj["cuil_funcionario"].str.len() == 11]
        base = _base_personas(ddjj).drop_duplicates("cuil_funcionario")
        a = base.merge(adj, on="cuil_funcionario", how="inner")
        if not a.empty:
            a = a.assign(cuit_sociedad=a["cuil_funcionario"], sociedad=a.get("proveedor_adjudicado", ""),
                         tipo_alerta="FUNCIONARIO_PROVEEDOR_ADJUDICADO", criticidad="ROJA",
                         descripcion="El CUIT del funcionario figura como proveedor adjudicado en el Boletín Oficial ("
                                     + a.get("organismo_contratante", "").fillna("").astype(str) + ", "
                                     + a.get("fecha", "").fillna("").astype(str) + ", "
                                     + a.get("monto_adjudicado_bora", "").fillna("").astype(str) + "). "
                                     + a.get("link_bora", "").fillna("").astype(str)
                                     + " Verificar incompatibilidad (Ley 25.188, art. 13).")
            partes.append(a)
        log.info(f"  Funcionarios adjudicados en BORA: {a['cuil_funcionario'].nunique() if not a.empty else 0}")

    if "proveedor_contratista" in ddjj.columns:
        p = _base_personas(ddjj)
        p = p[p["proveedor_contratista"].astype(str).str.strip().str.upper() == "SI"]
        p = p.drop_duplicates("cuil_funcionario")
        if not p.empty:
            p = p.assign(cuit_sociedad="", sociedad="", tipo_alerta="PROVEEDOR_CONTRATISTA_DECLARADO",
                         criticidad="AMARILLA",
                         descripcion="La DDJJ marca 'proveedor/contratista: SI'. Puede indicar que es "
                                     "proveedor del Estado o que interviene en contrataciones (p. ej. comisiones "
                                     "de recepción o evaluación). Verificar (Ley 25.188, art. 13).")
            partes.append(p)

    out = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    out = out.reindex(columns=COLS_ALERTA)
    out.to_csv(PROC_DIR / "alertas_conflicto.csv", index=False)
    log.info(f"  {len(out)} alertas de conflicto → alertas_conflicto.csv "
             f"({(out['criticidad'] == 'ROJA').sum()} rojas)")
    return out


# MAPPAP — Sistema de Monitoreo de Actividades Privadas y Públicas Anteriores y
# Posteriores a la función pública (Oficina Anticorrupción, datos.jus.gob.ar).
MAPPAP_BASE = ("https://datos.jus.gob.ar/dataset/eda31892-54f7-414d-9685-bd711b757895/resource/")
MAPPAP_PKG  = ("https://datos.jus.gob.ar/api/3/action/package_show?"
               "id=declaraciones-juradas-de-actividades-anteriores-y-posteriores-a-la-funcion-publica")
SECTORES_NO_PRIVADOS = ("administración pública", "administracion publica", "sin información",
                        "sin informacion", "educación, investigación", "educacion, investigacion")
VENTANA_DIAS = 365

# El campo "sector" del MAPPAP no distingue público de privado (bancos públicos,
# empresas del Estado y entes figuran como "Banco, finanzas", "Energético"...).
# Se excluyen por nombre los empleadores públicos, organismos internacionales y
# respuestas vacías.
_RE_PUBLICO = re.compile(
    r"MINISTERI|SECRETAR[IÍ]A|SUBSECRETAR|GOBIERNO|MUNICIPALIDAD|PROVINCIA DE|PCIA|"
    r"HONORABLE|C[AÁ]MARA DE (DIPUTADOS|SENADORES)|SENADO|LEGISLATURA|CONCEJO|PODER JUDICIAL|"
    r"CONSEJO DE LA MAGISTRATURA|JUZGADO|FISCAL[IÍ]A|DEFENSOR[IÍ]A|PROCURACI|TRIBUNAL|"
    r"ENTE |ENTE$|ENACOM|ENRE|ENARGAS|ENERGAS|INSTITUTO NACIONAL|INSTITUTO DE ENERG|ADMINISTRACI[OÓ]N NACIONAL|"
    r"DIRECCI[OÓ]N NACIONAL|AGENCIA NACIONAL|COMISI[OÓ]N NACIONAL|AUDITOR[IÍ]A GENERAL|SINDICATURA|"
    r"UNIVERSIDAD NACIONAL|UNIVERSIDAD DE BUENOS AIRES|\bUBA\b|CONICET|\bINTA\b|\bINTI\b|INCUCAI|INAREPS|"
    r"ANSES|\bAFIP\b|\bARCA\b|\bPAMI\b|\bINSSJP\b|BANCO CENTRAL|\bBCRA\b|BANCO DE LA NACI|"
    r"BANCO DE LA PROVINCIA|BANCO PROVINCIA|BANCO CIUDAD|BANCO DE INVERSI[OÓ]N Y COMERCIO|\bBICE\b|"
    r"PREFECTURA|GENDARMER|POLIC[IÍ]A|ARMADA|EJ[EÉ]RCITO|FUERZA A[EÉ]REA|ESTADO MAYOR|SERVICIO PENITENCIARIO|"
    r"HOSPITAL|HOSP\.|SOCIEDAD DEL ESTADO|\bS\.?E\.?$|NUCLEOEL[EÉ]CTRICA|\bARSAT\b|SOLUCIONES SATELITALES|"
    r"AEROL[IÍ]NEAS ARGENTINAS|ENERG[IÍ]A ARGENTINA|\bENARSA\b|\bYPF\b|CORREDORES VIALES|CORREO OFICIAL|"
    r"CORREO ARGENTINO|TRENES ARGENTINOS|OPERADORA FERROVIARIA|FERROCARRILES|BELGRANO CARGAS|\bADIF\b|\bSOFSE\b|"
    r"\bAYSA\b|AGUA Y SANEAMIENTOS ARGENTINOS|CASA DE MONEDA|INTERCARGO|FABRICACIONES MILITARES|DIOXITEK|"
    r"RADIO Y TELEVISI[OÓ]N ARGENTINA|\bTELAM\b|NACI[OÓ]N SEGUROS|COMISI[OÓ]N NACIONAL DE VALORES|"
    r"TEATRO SAN MART|TEATRO COL[OÓ]N|AUTORIDAD REGULATORIA|RADIO NACIONAL|\bRTA\b|PUERTOS|AUTORIDAD DE CUENCA|"
    r"OBRA SOCIAL DE LAS FUERZAS|\bIOSFA\b|\bOSEP\b|"
    r"BANCO INTERAMERICANO|\bBID\b|BANCO MUNDIAL|NACIONES UNIDAS|\bPNUD\b|\bOEA\b|\bCAF\b|\bFAO\b|UNICEF|"
    r"^(NO|NO APLICA|N/A|NINGUNO|MONOTRIBUTO|PERSONA F[IÍ]SICA|-+|\.+)$",
    re.IGNORECASE)


def descargar_mappap() -> dict:
    """Busca en el catálogo los CSV vigentes de actividades anteriores y
    posteriores (el nombre del archivo cambia con cada corte)."""
    out = {}
    headers = {"User-Agent": "monitor-ddjj/1.0"}
    urls = {}
    try:
        r = requests.get(MAPPAP_PKG, headers=headers, timeout=60)
        for res in r.json()["result"]["resources"]:
            u = res.get("url", "")
            if u.endswith(".csv") and "actividades-anteriores-funcion" in u:
                urls["anteriores"] = u
            elif u.endswith(".csv") and "actividades-posteriores-funcion" in u:
                urls["posteriores"] = u
    except Exception as e:
        log.warning(f"  MAPPAP: catálogo no disponible ({e})")
    for k in ("anteriores", "posteriores"):
        dest = RAW_DIR / f"mappap_{k}.csv"
        if k in urls:
            try:
                r = requests.get(urls[k], headers=headers, timeout=180)
                r.raise_for_status()
                dest.write_bytes(r.content)
                log.info(f"  MAPPAP {k}: {urls[k].rsplit('/', 1)[-1]}")
            except Exception as e:
                log.warning(f"  MAPPAP {k}: error de descarga ({e}) — uso caché si existe")
        if dest.exists():
            out[k] = pd.read_csv(dest, dtype=str, encoding="utf-8-sig")
    return out


def _es_privado(sector: pd.Series) -> pd.Series:
    s = sector.fillna("").str.lower().str.strip()
    return (s != "") & ~s.str.startswith(SECTORES_NO_PRIVADOS)


def cruce2_puertas_giratorias(ddjj: pd.DataFrame) -> pd.DataFrame:
    """Puerta giratoria: paso del sector privado a la función pública (o al revés)
    con menos de 365 días de diferencia, o empleo privado que CONTINÚA mientras
    ejerce el cargo. Fuente: DDJJ de actividades anteriores y posteriores (MAPPAP).
    Se excluyen empleadores del sector público y de educación/investigación
    (universidades, CONICET), donde no se puede distinguir público de privado."""
    log.info("Cruce 2 — Puertas Giratorias (MAPPAP)...")
    cols = ["cuil_funcionario", "nombre_funcionario", "organismo", "cargo", "cuit_sociedad",
            "sociedad", "sector_privado", "sentido", "fecha_cargo", "fecha_privado", "dias",
            "tipo_alerta", "criticidad", "descripcion"]
    m = descargar_mappap()
    filas = []

    a = m.get("anteriores", pd.DataFrame())
    if not a.empty:
        ini = pd.to_datetime(a["cargo_fecha_inicio"], errors="coerce")
        for pref, emp, cuit in (("relacion_dependencia", "relacion_dependencia_empleador", "relacion_dependencia_empleador_cuit"),
                                ("trabajo_independiente", "trabajo_independiente_razon_social", None)):
            nom = a[emp].fillna("").str.strip()
            priv = _es_privado(a[f"{pref}_sector"]) & (nom.str.len() > 2) & ~nom.str.contains(_RE_PUBLICO)
            cont = a[f"{pref}_continuidad"].fillna("").str.strip().str.lower().eq("si")
            cese = pd.to_datetime(a[f"{pref}_fecha_cese"], errors="coerce")
            dias = (ini - cese).dt.days
            ok = priv & (cont | dias.between(0, VENTANA_DIAS))
            x = a[ok]
            filas.append(pd.DataFrame({
                "cuil_funcionario": x["cuit_cuil"].map(_digitos),
                "nombre_funcionario": x["apellidos_nombres"],
                "organismo": x["cargo_jurisdiccion"], "cargo": x["cargo_actual"],
                "cuit_sociedad": x[cuit].map(_digitos) if cuit else "",
                "sociedad": x[emp], "sector_privado": x[f"{pref}_sector"],
                "sentido": cont[ok].map({True: "SIMULTANEO", False: "ENTRADA"}),
                "fecha_cargo": ini[ok].dt.date, "fecha_privado": cese[ok].dt.date,
                "dias": dias[ok],
            }))

    p = m.get("posteriores", pd.DataFrame())
    if not p.empty:
        fin = pd.to_datetime(p["cargo_fecha_cese"], errors="coerce")
        for pref, emp, cuit in (("relacion_dependencia", "relacion_dependencia_empleador", "relacion_dependencia_empleador_cuit"),
                                ("trabajo_independiente", "trabajo_independiente_razon_social", None)):
            nom = p[emp].fillna("").str.strip()
            priv = _es_privado(p[f"{pref}_sector"]) & (nom.str.len() > 2) & ~nom.str.contains(_RE_PUBLICO)
            inicio = pd.to_datetime(p[f"{pref}_fecha_inicio"], errors="coerce")
            dias = (inicio - fin).dt.days
            ok = priv & dias.between(0, VENTANA_DIAS)
            x = p[ok]
            filas.append(pd.DataFrame({
                "cuil_funcionario": x["cuit_cuil"].map(_digitos),
                "nombre_funcionario": x["apellidos_nombres"],
                "organismo": x["cargo_jurisdiccion"], "cargo": x["cargo_cese"],
                "cuit_sociedad": x[cuit].map(_digitos) if cuit else "",
                "sociedad": x[emp], "sector_privado": x[f"{pref}_sector"],
                "sentido": "SALIDA", "fecha_cargo": fin[ok].dt.date, "fecha_privado": inicio[ok].dt.date,
                "dias": dias[ok],
            }))

    out = pd.concat(filas, ignore_index=True) if filas else pd.DataFrame(columns=cols)
    if not out.empty:
        out = out[out["cuil_funcionario"].str.len() == 11].drop_duplicates(
            ["cuil_funcionario", "sociedad", "sentido"])
        desc = {"ENTRADA":    "Dejó un empleo/actividad privada menos de 365 días antes de asumir.",
                "SIMULTANEO": "Declara que continúa su empleo/actividad privada mientras ejerce el cargo.",
                "SALIDA":     "Pasó al sector privado menos de 365 días después de dejar el cargo."}
        out["tipo_alerta"] = "PUERTA_GIRATORIA"
        out["criticidad"]  = "AMARILLA"
        out["descripcion"] = out["sentido"].map(desc) + " Fuente: DDJJ de actividades (MAPPAP, OA)."
    out = out.reindex(columns=cols)
    out.to_csv(PROC_DIR / "alertas_puertas_giratorias.csv", index=False)
    log.info(f"  {len(out)} alertas puertas giratorias ({out['cuil_funcionario'].nunique()} personas) "
             f"→ alertas_puertas_giratorias.csv  {out['sentido'].value_counts().to_dict()}")
    return out


def run_cruces() -> dict:
    log.info("=" * 55)
    log.info("FASE 2 — CRUCES RELACIONALES")
    log.info("=" * 55)
    ddjj  = _cargar("ddjj_normalizada.csv")
    adjud = descargar_adjudicaciones()
    return {
        "conflicto":  cruce1_conflicto_interes(ddjj, adjud),
        "puertas":    cruce2_puertas_giratorias(ddjj),
    }


if __name__ == "__main__":
    r = run_cruces()
    print(f"Conflicto: {len(r['conflicto'])}  |  Puertas: {len(r['puertas'])}")
