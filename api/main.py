"""
api/main.py
━━━━━━━━━━━
API FastAPI — Monitor DDJJ
"""

import json
import os
from pathlib import Path
from typing import Optional
from datetime import datetime

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

BASE_DIR  = Path(__file__).resolve().parent.parent
PROC_DIR  = BASE_DIR / "data" / "processed"
FRONT_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="Monitor DDJJ",
    description="Análisis de riesgo en Declaraciones Juradas Patrimoniales — Argentina",
    version="2.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET","POST"], allow_headers=["*"])


# ── Helpers ───────────────────────────────────────────────────────────────

def _csv(nombre: str) -> pd.DataFrame:
    p = PROC_DIR / nombre
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def _rec(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def _mask_poder(org: pd.Series, poder: str) -> pd.Series:
    u = org.str.upper().fillna("")
    if poder == "EJECUTIVO":
        return ~u.str.contains("SENADO|DIPUTADOS|LEGISLAT|CONGRESO|JUDICIAL|TRIBUNAL|MAGISTRATURA|DEFENSOR|FISCAL")
    if poder == "LEGISLATIVO":
        return u.str.contains("SENADO|DIPUTADOS|LEGISLAT|CONGRESO")
    if poder == "JUDICIAL":
        return u.str.contains("JUDICIAL|TRIBUNAL|MAGISTRATURA|DEFENSOR|FISCAL")
    return pd.Series(True, index=org.index)


# ── Dashboard ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard():
    p = FRONT_DIR / "index.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "<h1>Monitor DDJJ</h1><p>Corré el pipeline para generar los datos.</p>"


# ── Resumen general ───────────────────────────────────────────────────────

@app.get("/api/resumen")
def resumen():
    sc  = _csv("scoring_riesgo.csv")
    c1  = _csv("alertas_conflicto.csv")
    c2  = _csv("alertas_puertas_giratorias.csv")
    ml  = _csv("anomalias_ml.csv")
    ind = _csv("indicadores_internacionales.csv")

    dist_f3  = sc["nivel_riesgo"].value_counts().to_dict() if not sc.empty and "nivel_riesgo" in sc.columns else {}
    dist_int = ind["nivel_internacional"].value_counts().to_dict() if not ind.empty and "nivel_internacional" in ind.columns else {}

    return {
        "timestamp":               datetime.utcnow().isoformat(),
        "total_funcionarios":      len(sc),
        "distribucion_riesgo_f3":  dist_f3,
        "distribucion_internacional": dist_int,
        "alertas_conflicto":       len(c1),
        "alertas_puertas":         len(c2),
        "anomalias_ml":            len(ml),
        "indicadores_calculados":  len(ind) > 0,
    }


# ── Scoring Fase 3 ────────────────────────────────────────────────────────

@app.get("/api/scoring")
def scoring(
    limite:    int           = Query(50, ge=1, le=500),
    nivel:     Optional[str] = Query(None),
    organismo: Optional[str] = Query(None),
):
    df = _csv("scoring_riesgo.csv")
    if df.empty:
        raise HTTPException(404, "Sin datos. Corré el pipeline.")
    if nivel and "nivel_riesgo" in df.columns:
        df = df[df["nivel_riesgo"] == nivel.upper()]
    if organismo and "organismo" in df.columns:
        df = df[df["organismo"].str.contains(organismo, case=False, na=False)]
    df = df.sort_values("score_riesgo", ascending=False).head(limite)
    return {"total": len(df), "datos": _rec(df)}


# ── Por poder del Estado ──────────────────────────────────────────────────

@app.get("/api/poder/{poder}")
def por_poder(
    poder: str,
    limite:    int           = Query(300, ge=1, le=1000),
    organismo: Optional[str] = Query(None),
    nivel:     Optional[str] = Query(None),
    buscar:    Optional[str] = Query(None),
):
    df = _csv("scoring_riesgo.csv")
    if df.empty:
        raise HTTPException(404, "Sin datos.")

    p = poder.upper()
    if p not in ("EJECUTIVO", "LEGISLATIVO", "JUDICIAL"):
        raise HTTPException(400, "Poder inválido. Usar: EJECUTIVO, LEGISLATIVO, JUDICIAL")

    df = df[_mask_poder(df["organismo"], p)]

    if organismo:
        df = df[df["organismo"].str.contains(organismo, case=False, na=False)]
    if nivel:
        df = df[df["nivel_riesgo"] == nivel.upper()]
    if buscar:
        mask_b = (
            df["funcionario_apellido_nombre"].str.contains(buscar, case=False, na=False) |
            df["organismo"].str.contains(buscar, case=False, na=False)
        )
        df = df[mask_b]

    df = df.sort_values("score_riesgo", ascending=False).head(limite)

    # Organismos únicos para filtro
    organismos = sorted(df["organismo"].dropna().unique().tolist()) if "organismo" in df.columns else []

    return {
        "total":      len(df),
        "poder":      p,
        "organismos": organismos[:100],
        "datos":      _rec(df),
    }


# ── Histórico por CUIT (2022-2023-2024) ──────────────────────────────────

@app.get("/api/historico/{cuit}")
def historico_funcionario(cuit: str):
    cuit_limpio = cuit.replace("-", "").replace(".0", "").strip()
    resultado = {}
    nombres = {
        "2022": "ddjj_2022_norm.csv",
        "2023": "ddjj_2023_norm.csv",
        "2024": "ddjj_normalizada.csv",
    }

    for anio, fname in nombres.items():
        df = _csv(fname)
        if df.empty:
            continue
        cuil_col = _col(df, ["cuit", "cuil", "cuil_declarante"])
        if not cuil_col:
            continue
        # normalizar CUIT para comparar
        serie = df[cuil_col].astype(str).str.replace("-","").str.replace(".0","").str.strip()
        mask = serie == cuit_limpio
        filas = df[mask]
        if filas.empty:
            continue
        # Preferir declaración anual (tipo 1) sobre inicial (tipo 0)
        if "tipo_declaracion_jurada_id" in filas.columns:
            anuales = filas[filas["tipo_declaracion_jurada_id"].astype(str).isin(["1","1.0"])]
            fila = anuales.iloc[0] if not anuales.empty else filas.iloc[0]
        else:
            fila = filas.iloc[0]
        resultado[anio] = json.loads(fila.to_json(force_ascii=False))

    if not resultado:
        raise HTTPException(404, f"CUIT {cuit} no encontrado en ningún año.")

    # Calcular evolución
    evolucion = {}
    TC = 900.0
    for anio, row in resultado.items():
        pn = row.get("total_bienes_final") or row.get("pn_actual")
        ing = row.get("total_ingreso_neto_c1234") or row.get("ingresos_neto_gastos") or row.get("ingresos")
        evolucion[anio] = {
            "pn_nominal": pn,
            "pn_usd":     round(pn / TC, 2) if pn else None,
            "ingresos":   ing,
        }

    return {
        "cuit":      cuit,
        "evolucion": evolucion,
        "anos":      resultado,
    }


# ── Alertas Fase 2 ────────────────────────────────────────────────────────

@app.get("/api/alertas")
def alertas(tipo: Optional[str] = Query(None)):
    c1 = _csv("alertas_conflicto.csv")
    c2 = _csv("alertas_puertas_giratorias.csv")
    if tipo and tipo.upper() == "CONFLICTO":
        return {"total": len(c1), "datos": _rec(c1)}
    if tipo and tipo.upper() == "PUERTAS":
        return {"total": len(c2), "datos": _rec(c2)}
    todas = pd.concat([c1, c2], ignore_index=True)
    return {"total": len(todas), "datos": _rec(todas)}


# ── Perfil funcionario ────────────────────────────────────────────────────

@app.get("/api/funcionario/{cuil}")
def perfil_funcionario(cuil: str):
    sc = _csv("perfil_riesgo_completo.csv")
    if sc.empty:
        sc = _csv("scoring_riesgo.csv")
    if sc.empty:
        raise HTTPException(404, "Sin datos")

    cuil_col = _col(sc, ["cuil", "cuil_declarante"])
    if not cuil_col:
        raise HTTPException(404, "Sin columna CUIL")

    mask = sc[cuil_col].astype(str).str.replace("-","") == cuil.replace("-","")
    if not mask.any():
        raise HTTPException(404, f"Funcionario {cuil} no encontrado")

    row = _rec(sc[mask])[0]

    alertas_func = []
    for fname in ["alertas_conflicto.csv", "alertas_puertas_giratorias.csv"]:
        df_al = _csv(fname)
        if df_al.empty: continue
        c_al = _col(df_al, ["cuil_funcionario"])
        if c_al:
            sub = df_al[df_al[c_al].astype(str).str.replace("-","") == cuil.replace("-","")]
            alertas_func.extend(_rec(sub))

    return {"perfil": row, "alertas": alertas_func}


# ── Judicial ──────────────────────────────────────────────────────────────

@app.get("/api/judicial")
def judicial(
    limite:   int           = Query(1000, ge=1, le=2000),
    provincia: Optional[str] = Query(None),
    cargo:    Optional[str] = Query(None),
    buscar:   Optional[str] = Query(None),
):
    df = _csv("tabla_judicial.csv")
    if df.empty:
        raise HTTPException(404, "Sin datos judiciales. Corré fase 1.")
    if provincia:
        df = df[df["provincia"].str.contains(provincia, case=False, na=False)]
    if cargo:
        df = df[df["cargo"].str.contains(cargo, case=False, na=False)]
    if buscar:
        df = df[
            df["nombre"].str.contains(buscar, case=False, na=False) |
            df["organismo"].str.contains(buscar, case=False, na=False)
        ]
    provincias = sorted(df["provincia"].dropna().unique().tolist()) if "provincia" in df.columns else []
    return {"total": len(df), "provincias": provincias, "datos": _rec(df.head(limite))}


# ── Grafo / ML ────────────────────────────────────────────────────────────

@app.get("/api/grafo")
def grafo():
    p = PROC_DIR / "red_societaria.json"
    if not p.exists():
        raise HTTPException(404, "Grafo no generado.")
    return JSONResponse(content=json.loads(p.read_text(encoding="utf-8")))


@app.get("/api/anomalias")
def anomalias():
    df = _csv("anomalias_ml.csv")
    if df.empty:
        raise HTTPException(404, "Sin anomalías.")
    return {"total": len(df), "datos": _rec(df)}


@app.get("/api/clusters")
def clusters():
    df = _csv("clusters_riesgo.csv")
    if df.empty:
        raise HTTPException(404, "Sin clusters.")
    return {"total": len(df), "datos": _rec(df)}


# ── Indicadores Internacionales ───────────────────────────────────────────

@app.get("/api/indicadores/resumen")
def indicadores_resumen():
    df = _csv("indicadores_internacionales.csv")
    if df.empty:
        raise HTTPException(404, "Sin indicadores.")
    from scripts.indicadores_internacionales import resumen_json
    return resumen_json(df)


@app.get("/api/indicadores/ranking")
def indicadores_ranking(
    limite:    int           = Query(50, ge=1, le=500),
    nivel:     Optional[str] = Query(None),
    marco:     Optional[str] = Query(None),
    organismo: Optional[str] = Query(None),
):
    df = _csv("indicadores_internacionales.csv")
    if df.empty:
        raise HTTPException(404, "Sin indicadores")
    if nivel:
        df = df[df["nivel_internacional"].eq(nivel.upper())]
    if organismo and "organismo" in df.columns:
        df = df[df["organismo"].str.contains(organismo, case=False, na=False)]
    col_ord = f"score_{marco.lower()}" if marco and f"score_{marco.lower()}" in df.columns else "score_internacional"
    df = df.sort_values(col_ord, ascending=False).head(limite)
    return {"total": len(df), "ordenado_por": col_ord, "datos": _rec(df)}


@app.get("/api/indicadores/funcionario/{cuil}")
def indicadores_funcionario(cuil: str):
    df = _csv("perfil_riesgo_completo.csv")
    if df.empty:
        df = _csv("indicadores_internacionales.csv")
    if df.empty:
        raise HTTPException(404, "Sin datos de indicadores")

    cuil_col = _col(df, ["cuil", "cuil_declarante"])
    if not cuil_col:
        raise HTTPException(404, "Sin columna CUIL")

    mask = df[cuil_col].astype(str).str.replace("-","") == cuil.replace("-","")
    if not mask.any():
        raise HTTPException(404, f"Funcionario {cuil} no encontrado")

    row = _rec(df[mask])[0]
    breakdown = {
        "FATF":  {"score": row.get("score_fatf",0), "A1_pep": {"score":row.get("A1_pep",0),"bandera":row.get("A1_pep_bandera","VERDE")}, "A2_beneficial_ow": {"score":row.get("A2_beneficial_ow",0),"bandera":row.get("A2_beneficial_ow_bandera","VERDE")}, "A3_cash_ratio": {"score":row.get("A3_cash_ratio",0),"bandera":row.get("A3_cash_ratio_bandera","VERDE")}, "A4_jurisdiccion": {"score":row.get("A4_jurisdiccion",0),"bandera":row.get("A4_jurisdiccion_bandera","VERDE")}},
        "World_Bank": {"score": row.get("score_wb",0), "B1_pares_lac": {"score":row.get("B1_pares_lac",0),"bandera":row.get("B1_pares_lac_bandera","VERDE")}, "B2_brecha_sal": {"score":row.get("B2_brecha_sal",0),"bandera":row.get("B2_brecha_sal_bandera","VERDE")}},
        "TI":    {"score": row.get("score_ti",0), "C1_velocidad": {"score":row.get("C1_velocidad",0),"bandera":row.get("C1_velocidad_bandera","VERDE")}, "C2_sector": {"score":row.get("C2_sector",0),"bandera":row.get("C2_sector_bandera","VERDE")}},
        "OCDE":  {"score": row.get("score_ocde",0), "D1_completitud": {"score":row.get("D1_completitud",0),"bandera":row.get("D1_completitud_bandera","VERDE")}, "D2_conflicto": {"score":row.get("D2_conflicto",0),"bandera":row.get("D2_conflicto_bandera","VERDE")}, "D3_puerta": {"score":row.get("D3_puerta",0),"bandera":row.get("D3_puerta_bandera","VERDE")}, "D4_evolucion": {"score":row.get("D4_evolucion",0),"bandera":row.get("D4_evolucion_bandera","VERDE")}},
    }
    return {"perfil": row, "breakdown_por_marco": breakdown, "score_internacional": row.get("score_internacional",0), "nivel_internacional": row.get("nivel_internacional","BAJO")}


@app.get("/api/indicadores/contexto-lac")
def contexto_lac():
    return {
        "argentina": {"cpi_ti_2023":38,"wb_cci_percentil":43.8,"fatf_estado":"Lista gris retirada 2023","ocde_miembro":False,"ocde_adherente_pac":True},
        "referencia_lac": {"cpi_promedio_lac":43,"wb_cci_percentil_lac":49.3,"mejor_cpi_lac":{"pais":"Uruguay","cpi":74},"peor_cpi_lac":{"pais":"Venezuela","cpi":13}},
        "fuentes": {"FATF":"https://www.fatf-gafi.org","WB":"https://info.worldbank.org/governance/wgi/","TI":"https://www.transparency.org/en/cpi/2023","OCDE":"https://www.oecd.org/gov/ethics/"},
    }


# ── Run pipeline ──────────────────────────────────────────────────────────

@app.post("/api/run-pipeline")
def run_pipeline_endpoint(
    fases: list[int] = [1, 2, 3, 4],
    x_pipeline_token: Optional[str] = Header(None),
):
    token = os.getenv("PIPELINE_TOKEN", "dev-token")
    if x_pipeline_token != token:
        raise HTTPException(401, "Token inválido")
    import subprocess, sys
    cmd = [sys.executable, str(BASE_DIR / "pipeline.py"), "--fase"] + [str(f) for f in fases]
    proc = subprocess.Popen(cmd, capture_output=True, text=True, cwd=str(BASE_DIR))
    stdout, stderr = proc.communicate(timeout=600)
    return {"status": "ok" if proc.returncode == 0 else "error", "returncode": proc.returncode, "stdout": stdout[-3000:], "stderr": stderr[-1000:] if stderr else None}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)