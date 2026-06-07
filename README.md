# Monitor DDJJ — Declaraciones Juradas Patrimoniales

Análisis de riesgo sobre DDJJ de funcionarios argentinos.
Datos 100% públicos — Fuente: Portal de Datos Abiertos OA / datos.gob.ar

---

## Estructura

```
monitor_ddjj/
├── pipeline.py                       ← orquestador principal
├── requirements.txt
├── Dockerfile                        ← Railway deploy
├── .env.example
│
├── scripts/
│   ├── fase1_etl.py                  ← descarga OA + BCRA, deflacta USD
│   ├── fase2_cruces.py               ← conflicto interés + puertas giratorias
│   ├── fase3_scoring.py              ← IVPI + opacidad + fuga → score 0-100
│   ├── fase4_ml.py                   ← Isolation Forest + SVM + grafos
│   └── indicadores_internacionales.py ← 12 indicadores FATF/WB/TI/OCDE
│
├── api/
│   └── main.py                       ← FastAPI — todos los endpoints
│
├── frontend/
│   └── index.html                    ← dashboard
│
├── data/
│   ├── raw/                          ← CSVs descargados (caché)
│   └── processed/                    ← salidas de cada fase
│
└── .github/workflows/
    └── pipeline_diario.yml           ← cron 06:00 UTC
```

---

## Fases y salidas

| Fase | Script | Salida |
|------|--------|--------|
| 1 — ETL | `fase1_etl.py` | `ddjj_normalizada.csv`, `sujetos_obligados_clean.csv` |
| 2 — Cruces | `fase2_cruces.py` | `alertas_conflicto.csv`, `alertas_puertas_giratorias.csv` |
| 3 — Scoring | `fase3_scoring.py` | `scoring_riesgo.csv` |
| 4 — ML | `fase4_ml.py` | `anomalias_ml.csv`, `red_societaria.json`, `clusters_riesgo.csv` |
| 5 — Indicadores | `indicadores_internacionales.py` | `indicadores_internacionales.csv`, `perfil_riesgo_completo.csv` |

---

## 12 Indicadores Internacionales

### FATF / GAFI
| ID | Indicador | Umbral | Peso |
|----|-----------|--------|------|
| A1 | PEP Screening (R.12) | Cargo en lista PEP nivel 1 | 8% |
| A2 | Beneficial Ownership (R.24/25) | Sociedad sin titular real explícito | 7% |
| A3 | Cash Ratio | >30% del patrimonio en efectivo | 8% |
| A4 | Jurisdicción de riesgo | Activos en lista gris/negra FATF 2024 | 7% |

### World Bank CCI (WGI 2024 — AR percentil 43.8)
| ID | Indicador | Umbral | Peso |
|----|-----------|--------|------|
| B1 | Percentil vs. pares LAC | >P80 del mismo cargo | 10% |
| B2 | Brecha salario/patrimonio | >10× ingreso oficial acumulado | 10% |

### Transparency International CPI 2023 (AR = 38/100)
| ID | Indicador | Umbral | Peso |
|----|-----------|--------|------|
| C1 | Velocidad de acumulación | >1.2× ingreso/año (ajustado CPI<40) | 10% |
| C2 | Sector de riesgo TI | Organismo en obra pública / contratos / energía | 5% |

### OCDE — Recomendación de Integridad Pública 2017
| ID | Indicador | Umbral | Peso |
|----|-----------|--------|------|
| D1 | Completitud declaratoria | Campos obligatorios incompletos | 5% |
| D2 | Conflicto de interés | Participación societaria en sector regulado | 13% |
| D3 | Puerta giratoria | Cambio cargo público → privado < 365 días | 10% |
| D4 | Evolución patrimonial acumulada | >1.5× ingreso/año de mandato | 7% |

---

## Correr en PyCharm

```bash
# 1. Instalar
pip install -r requirements.txt

# 2. Configurar
cp .env.example .env

# 3. Pipeline completo (fases 1-4 + indicadores)
python pipeline.py

# 4. Fase individual
python pipeline.py --fase 1
python pipeline.py --fase 5       # solo indicadores

# 5. API
uvicorn api.main:app --reload --port 8000
# http://localhost:8000
# http://localhost:8000/docs
```

---

## Deploy Railway

1. Push al repo GitHub
2. Railway → nuevo proyecto → conectar repo
3. Railway detecta el `Dockerfile` automáticamente
4. Variable de entorno: `PIPELINE_TOKEN=<tu-token>`
5. El workflow de GitHub Actions corre a las 06:00 UTC y sube los datos

---

## Endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Dashboard |
| GET | `/api/resumen` | KPIs generales |
| GET | `/api/scoring` | Ranking Fase 3 |
| GET | `/api/alertas` | Alertas Fase 2 |
| GET | `/api/funcionario/{cuil}` | Perfil |
| GET | `/api/grafo` | Red societaria |
| GET | `/api/anomalias` | ML anomalías |
| GET | `/api/clusters` | Clusters |
| GET | `/api/indicadores/resumen` | KPIs internacionales |
| GET | `/api/indicadores/ranking` | Ranking por score int. |
| GET | `/api/indicadores/funcionario/{cuil}` | Breakdown por marco |
| GET | `/api/indicadores/contexto-lac` | Argentina vs. LAC |
| POST | `/api/run-pipeline` | Dispara pipeline |

---

## Disclaimer

Herramienta experimental y académica.
Los resultados son indicadores algorítmicos de riesgo — no implican
juicio legal, acusación ni determinación de responsabilidad.
Datos amparados por Ley 27.275 de Acceso a la Información Pública.
