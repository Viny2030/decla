"""
api/main.py
━━━━━━━━━━━
API FastAPI — Monitor DDJJ
Sirve el dashboard y expone los datos de las 4 fases + indicadores internacionales.

GET  /                              → dashboard HTML
GET  /api/resumen                   → KPIs generales
GET  /api/scoring                   → ranking Fase 3
GET  /api/alertas                   → alertas Fases 2
GET  /api/funcionario/{cuil}        → perfil completo
GET  /api/grafo                     → red societaria JSON
GET  /api/anomalias                 → anomalías ML
GET  /api/clusters                  → clusters societarios
GET  /api/indicadores/resumen       → KPIs indicadores internacionales
GET  /api/indicadores/ranking       → ranking por score internacional
GET  /api/indicadores/funcionario/{cuil}  → breakdown por marco
GET  /api/indicadores/contexto-lac  → Argentina vs LAC
POST /api/run-pipeline              → dispara pipeline (token requerido)
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
    version="1.1.0",
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
    nivel:     Optional[str] = Query(None, description="CRÍTICO|ALTO|MEDIO|BAJO"),
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


# ── Alertas Fase 2 ────────────────────────────────────────────────────────

@app.get("/api/alertas")
def alertas(tipo: Optional[str] = Query(None, description="CONFLICTO|PUERTAS")):
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
    sc  = _csv("perfil_riesgo_completo.csv")
    if sc.empty:
        sc = _csv("scoring_riesgo.csv")
    if sc.empty:
        raise HTTPException(404, "Sin datos")

    cuil_col = _col(sc, ["cuil", "cuil_declarante"])
    if not cuil_col:
        raise HTTPException(404, "Sin columna CUIL")

    mask = sc[cuil_col].astype(str).str.replace("-", "") == cuil.replace("-", "")
    if not mask.any():
        raise HTTPException(404, f"Funcionario {cuil} no encontrado")

    row = _rec(sc[mask])[0]

    # Alertas del funcionario
    alertas_func = []
    for fname in ["alertas_conflicto.csv", "alertas_puertas_giratorias.csv"]:
        df_al = _csv(fname)
        if df_al.empty: continue
        c_al = _col(df_al, ["cuil_funcionario"])
        if c_al:
            sub = df_al[df_al[c_al].astype(str).str.replace("-","") == cuil.replace("-","")]
            alertas_func.extend(_rec(sub))

    return {"perfil": row, "alertas": alertas_func}


# ── Grafo / ML ────────────────────────────────────────────────────────────

@app.get("/api/grafo")
def grafo():
    p = PROC_DIR / "red_societaria.json"
    if not p.exists():
        raise HTTPException(404, "Grafo no generado. Corré fase 4.")
    return JSONResponse(content=json.loads(p.read_text(encoding="utf-8")))


@app.get("/api/anomalias")
def anomalias():
    df = _csv("anomalias_ml.csv")
    if df.empty:
        raise HTTPException(404, "Sin anomalías. Corré fase 4.")
    return {"total": len(df), "datos": _rec(df)}


@app.get("/api/clusters")
def clusters():
    df = _csv("clusters_riesgo.csv")
    if df.empty:
        raise HTTPException(404, "Sin clusters. Corré fase 4.")
    return {"total": len(df), "datos": _rec(df)}


# ── Indicadores Internacionales ───────────────────────────────────────────

@app.get("/api/indicadores/resumen")
def indicadores_resumen():
    df = _csv("indicadores_internacionales.csv")
    if df.empty:
        raise HTTPException(404, "Sin indicadores. Corré indicadores_internacionales.py")

    from scripts.indicadores_internacionales import resumen_json, FATF_CASH_UMBRAL, OCDE_UMBRAL_ACUM, TI_VELOCIDAD_BM, TI_AR_CPI, WB_AR_PERCENTIL, WB_LAC_PERCENTIL
    return resumen_json(df)


@app.get("/api/indicadores/ranking")
def indicadores_ranking(
    limite:    int           = Query(50, ge=1, le=500),
    nivel:     Optional[str] = Query(None, description="CRÍTICO|ALTO|MEDIO|BAJO"),
    marco:     Optional[str] = Query(None, description="fatf|wb|ti|ocde"),
    organismo: Optional[str] = Query(None),
):
    df = _csv("indicadores_internacionales.csv")
    if df.empty:
        raise HTTPException(404, "Sin indicadores")

    if nivel:
        df = df[df.get("nivel_internacional", pd.Series()).eq(nivel.upper())]
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
        "FATF": {
            "score": row.get("score_fatf", 0),
            "A1_pep":          {"score": row.get("A1_pep", 0),           "bandera": row.get("A1_pep_bandera", "VERDE")},
            "A2_beneficial_ow":{"score": row.get("A2_beneficial_ow", 0), "bandera": row.get("A2_beneficial_ow_bandera", "VERDE")},
            "A3_cash_ratio":   {"score": row.get("A3_cash_ratio", 0),    "bandera": row.get("A3_cash_ratio_bandera", "VERDE")},
            "A4_jurisdiccion": {"score": row.get("A4_jurisdiccion", 0),  "bandera": row.get("A4_jurisdiccion_bandera", "VERDE")},
        },
        "World_Bank": {
            "score": row.get("score_wb", 0),
            "B1_pares_lac":  {"score": row.get("B1_pares_lac", 0),  "bandera": row.get("B1_pares_lac_bandera", "VERDE")},
            "B2_brecha_sal": {"score": row.get("B2_brecha_sal", 0), "bandera": row.get("B2_brecha_sal_bandera", "VERDE")},
        },
        "TI": {
            "score": row.get("score_ti", 0),
            "C1_velocidad": {"score": row.get("C1_velocidad", 0), "bandera": row.get("C1_velocidad_bandera", "VERDE")},
            "C2_sector":    {"score": row.get("C2_sector", 0),    "bandera": row.get("C2_sector_bandera", "VERDE")},
        },
        "OCDE": {
            "score": row.get("score_ocde", 0),
            "D1_completitud": {"score": row.get("D1_completitud", 0), "bandera": row.get("D1_completitud_bandera", "VERDE")},
            "D2_conflicto":   {"score": row.get("D2_conflicto", 0),   "bandera": row.get("D2_conflicto_bandera", "VERDE")},
            "D3_puerta":      {"score": row.get("D3_puerta", 0),      "bandera": row.get("D3_puerta_bandera", "VERDE")},
            "D4_evolucion":   {"score": row.get("D4_evolucion", 0),   "bandera": row.get("D4_evolucion_bandera", "VERDE")},
        },
    }

    return {
        "perfil":              row,
        "breakdown_por_marco": breakdown,
        "score_internacional": row.get("score_internacional", 0),
        "nivel_internacional": row.get("nivel_internacional", "BAJO"),
    }


@app.get("/api/indicadores/contexto-lac")
def contexto_lac():
    return {
        "argentina": {
            "cpi_ti_2023":          38,
            "cpi_ti_2022":          38,
            "wb_cci_percentil":     43.8,
            "wb_cci_score":        -0.28,
            "fatf_estado":         "Lista gris retirada 2023 — en seguimiento",
            "ocde_miembro":         False,
            "ocde_adherente_pac":   True,
        },
        "referencia_lac": {
            "cpi_promedio_lac":      43,
            "wb_cci_percentil_lac":  49.3,
            "mejor_cpi_lac":         {"pais": "Uruguay", "cpi": 74},
            "peor_cpi_lac":          {"pais": "Venezuela", "cpi": 13},
        },
        "umbrales_aplicados": {
            "FATF_cash_ratio":       "30% patrimonio en efectivo",
            "FATF_lista_gris_2024":  "Bulgaria, Camerún, Croacia, Siria, Vietnam, Yemen, RDC, Sudáfrica",
            "FATF_lista_negra_2024": "Corea del Norte, Irán, Myanmar",
            "WB_brecha_salario":     "Patrimonio > 10× ingreso oficial acumulado",
            "TI_velocidad_bm":       "1.2× ingreso/año (ajustado por CPI < 40)",
            "OCDE_acumulacion":      "1.5× ingreso/año de mandato",
            "OCDE_puerta_giratoria": "Ventana de 365 días post-cargo",
        },
        "fuentes": {
            "FATF":  "https://www.fatf-gafi.org/en/topics/high-risk-jurisdictions.html",
            "WB":    "https://info.worldbank.org/governance/wgi/",
            "TI":    "https://www.transparency.org/en/cpi/2023",
            "OCDE":  "https://www.oecd.org/gov/ethics/recommendation-public-integrity/",
        },
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
    return {
        "status":     "ok" if proc.returncode == 0 else "error",
        "returncode": proc.returncode,
        "stdout":     stdout[-3000:],
        "stderr":     stderr[-1000:] if stderr else None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
