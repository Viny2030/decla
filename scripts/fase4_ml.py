"""
scripts/fase4_ml.py
━━━━━━━━━━━━━━━━━━━
Fase 4 — Detección de Anomalías con Machine Learning
  · Isolation Forest + One-Class SVM (scikit-learn)
  · Análisis de Grafos: Funcionarios ↔ Sociedades (networkx)

Salidas:
  data/processed/anomalias_ml.csv
  data/processed/red_societaria.json
  data/processed/clusters_riesgo.csv
"""

import json
import logging
import warnings
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="[ML] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
PROC_DIR = BASE_DIR / "data" / "processed"


def _cargar(nombre: str) -> pd.DataFrame:
    p = PROC_DIR / nombre
    return pd.read_csv(p, low_memory=False) if p.exists() else pd.DataFrame()


def _col(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    for c in candidatos:
        if c in df.columns:
            return c
    return None


def preparar_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    feature_cols = [c for c in df.columns if any(
        k in c for k in ["ivpi", "opacidad_ratio", "fuga_ratio", "score_riesgo",
                          "pn_actual", "pn_ant", "delta_pn", "ingresos"]
    )]
    if not feature_cols:
        return pd.DataFrame(), []

    X = df[feature_cols].copy()
    X = X.apply(pd.to_numeric, errors="coerce")
    X = X.dropna(axis=1, how="all")
    if X.empty:
        return pd.DataFrame(), []

    feature_cols_validas = list(X.columns)
    X_imp    = SimpleImputer(strategy="median").fit_transform(X)
    X_scaled = StandardScaler().fit_transform(X_imp)
    log.info(f"Features: {feature_cols_validas}")
    return pd.DataFrame(X_scaled, columns=feature_cols_validas, index=df.index), feature_cols_validas


def isolation_forest(df: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    if X.empty:
        return df
    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42, n_jobs=-1)
    df["if_label"]    = model.fit_predict(X)
    df["if_score"]    = model.decision_function(X)
    df["anomalia_if"] = df["if_label"] == -1
    log.info(f"Isolation Forest: {df['anomalia_if'].sum()} anomalías")
    return df


def one_class_svm(df: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    if X.empty:
        return df
    model = OneClassSVM(kernel="rbf", nu=0.05, gamma="scale")
    df["svm_label"]    = model.fit_predict(X)
    df["anomalia_svm"] = df["svm_label"] == -1
    log.info(f"One-Class SVM: {df['anomalia_svm'].sum()} anomalías")
    return df


def consenso(df: pd.DataFrame) -> pd.DataFrame:
    if "anomalia_if" in df.columns and "anomalia_svm" in df.columns:
        df["anomalia_consenso"] = df["anomalia_if"] & df["anomalia_svm"]
        log.info(f"Consenso IF ∩ SVM: {df['anomalia_consenso'].sum()} anomalías")
    return df


def construir_grafo(ddjj: pd.DataFrame) -> nx.Graph:
    G = nx.Graph()
    cuil_col   = _col(ddjj, ["cuil", "cuil_declarante"])
    nombre_col = _col(ddjj, ["apellido_nombre", "nombre"])
    cuit_cols  = [c for c in ddjj.columns if any(
        k in c for k in ["cuit_soc", "sociedad", "participacion"]
    )]

    if not cuil_col:
        return G

    for _, row in ddjj.iterrows():
        cuil   = str(row.get(cuil_col, "")).strip()
        nombre = str(row.get(nombre_col, cuil)).strip() if nombre_col else cuil
        if not cuil or cuil == "nan":
            continue
        G.add_node(cuil, tipo="funcionario", nombre=nombre)
        for col in cuit_cols:
            cuit = str(row.get(col, "")).strip()
            if cuit and cuit != "nan":
                G.add_node(cuit, tipo="sociedad")
                G.add_edge(cuil, cuit, relacion="participacion")

    log.info(f"Grafo: {G.number_of_nodes()} nodos, {G.number_of_edges()} aristas")
    return G


def detectar_clusters(G: nx.Graph) -> pd.DataFrame:
    soc_multi = [(n, G.degree(n)) for n, d in G.nodes(data=True)
                 if d.get("tipo") == "sociedad" and G.degree(n) > 1]
    soc_multi.sort(key=lambda x: x[1], reverse=True)

    clusters = []
    for cuit_soc, grado in soc_multi[:50]:
        funcionarios = [
            G.nodes[v]["nombre"] for v in G.neighbors(cuit_soc)
            if G.nodes[v].get("tipo") == "funcionario"
        ]
        clusters.append({
            "cuit_sociedad":           cuit_soc,
            "funcionarios_vinculados": "; ".join(funcionarios),
            "cantidad_funcionarios":   grado,
            "criticidad":              "ROJA" if grado >= 3 else "AMARILLA",
        })
    return pd.DataFrame(clusters)


def run_ml() -> dict:
    log.info("=" * 55)
    log.info("FASE 4 — ML + GRAFOS")
    log.info("=" * 55)

    df_score = _cargar("scoring_riesgo.csv")
    ddjj     = _cargar("ddjj_normalizada.csv")

    anomalias = pd.DataFrame()
    if not df_score.empty:
        X, _ = preparar_features(df_score)
        if not X.empty:
            df_score = isolation_forest(df_score, X)
            df_score = one_class_svm(df_score, X)
            df_score = consenso(df_score)
            mask = df_score.get("anomalia_consenso", pd.Series(False))
            anomalias = df_score[mask].copy()
            anomalias.to_csv(PROC_DIR / "anomalias_ml.csv", index=False)

    clusters = pd.DataFrame()
    if not ddjj.empty:
        G = construir_grafo(ddjj)
        data = nx.node_link_data(G)
        (PROC_DIR / "red_societaria.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        clusters = detectar_clusters(G)
        if not clusters.empty:
            clusters.to_csv(PROC_DIR / "clusters_riesgo.csv", index=False)

    log.info(f"Anomalías ML: {len(anomalias)}  |  Clusters: {len(clusters)}")
    return {"anomalias_ml": anomalias, "clusters": clusters}


if __name__ == "__main__":
    run_ml()