"""
scripts/listas_gafi.py
Listas del GAFI/FATF (no se actualizan solas: revisar después de cada plenario,
febrero / junio / octubre).

Fuente: https://www.fatf-gafi.org/en/publications/High-risk-and-other-monitored-jurisdictions/increased-monitoring-june-2026.html
Vigentes al plenario del 19-jun-2026.
"""
import unicodedata

LISTAS_FECHA = "19-jun-2026"

# "Jurisdictions under Increased Monitoring" (lista gris) — 22 jurisdicciones
LISTA_GRIS = {
    "angola", "bolivia", "bosnia y herzegovina", "bulgaria", "camerun",
    "costa de marfil", "republica democratica del congo", "haiti", "irak",
    "kenia", "kuwait", "laos", "libano", "monaco", "nepal",
    "papua nueva guinea", "sudan del sur", "siria", "venezuela", "vietnam",
    "islas virgenes britanicas", "yemen",
}
# "High-Risk Jurisdictions subject to a Call for Action" (lista negra)
LISTA_NEGRA = {"iran", "corea del norte", "myanmar"}

_ALIAS = {
    "iraq": "irak", "kenya": "kenia", "lao": "laos", "republica democratica popular lao": "laos",
    "cote d'ivoire": "costa de marfil", "birmania": "myanmar", "myanmar (birmania)": "myanmar",
    "corea del norte (republica popular democratica de corea)": "corea del norte",
    "congo, republica democratica del": "republica democratica del congo",
    "islas virgenes (reino unido)": "islas virgenes britanicas",
}


def normalizar_pais(p) -> str:
    s = unicodedata.normalize("NFKD", str(p or "")).encode("ascii", "ignore").decode().lower().strip()
    s = " ".join(s.split())
    return _ALIAS.get(s, s)


def riesgo_pais(p) -> str:
    """'NEGRA', 'GRIS' o '' para un nombre de país en castellano."""
    n = normalizar_pais(p)
    if n in LISTA_NEGRA:
        return "NEGRA"
    if n in LISTA_GRIS:
        return "GRIS"
    return ""
