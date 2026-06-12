"""
constancia.py — Consulta de Constancia de Inscripción (ws_sr_constancia_inscripcion)
ARCA — ex AFIP

Uso básico:
    from scripts.arca.constancia import ConsultaConstancia

    cliente = ConsultaConstancia()            # homologación (lee env ARCA_CERT / ARCA_KEY)
    cliente = ConsultaConstancia(prod=True)   # producción
    resultado = cliente.get_persona(20123456789)
    print(resultado["datosGenerales"]["nombre"])
"""

import os
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from lxml import etree
import requests

from .wsaa import get_ticket

urllib3.disable_warnings()

# ── Endpoints ──────────────────────────────────────────────────────────────────
WSCI_URL_HOMO = "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA5"
WSCI_URL_PROD = "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA5"

SERVICE_ID = "ws_sr_constancia_inscripcion"


# ── SSL Adapter para servidores AFIP con DH key pequeña ───────────────────────

class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers="DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", LegacySSLAdapter())
    return session


class ConsultaConstancia:
    """
    Cliente para ws_sr_constancia_inscripcion de ARCA.

    Variables de entorno requeridas (o pasadas al constructor):
        ARCA_CERT   ruta a .crt  O  contenido PEM directo
        ARCA_KEY    ruta a .key  O  contenido PEM directo
        ARCA_PROD   "1" = producción  (opcional, default homologación)

    Métodos:
        dummy()               → verifica disponibilidad del servicio
        get_persona(cuit)     → dict con todos los datos de la constancia
        get_personas(cuits)   → idem para una lista de CUITs
    """

    def __init__(
        self,
        cert_path: str = None,
        key_path: str = None,
        prod: bool = None,
    ):
        self.cert_path = cert_path or os.environ["ARCA_CERT"]
        self.key_path  = key_path  or os.environ["ARCA_KEY"]
        if prod is None:
            prod = os.getenv("ARCA_PROD", "0") == "1"
        self.prod    = prod
        self.url     = WSCI_URL_PROD if prod else WSCI_URL_HOMO
        self._ticket = None
        self._session = _make_session()

    # ── Autenticación ──────────────────────────────────────────────────────────

    def _get_auth(self) -> tuple[str, str]:
        self._ticket = get_ticket(
            SERVICE_ID,
            cert_path=self.cert_path,
            key_path=self.key_path,
            prod=self.prod,
        )
        return self._ticket["token"], self._ticket["sign"]

    # ── SOAP ───────────────────────────────────────────────────────────────────

    def _call(self, body_inner: str) -> etree._Element:
        token, sign = self._get_auth()

        soap = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:a5="http://a5.soap.ws.server.puc.sr/">
  <soapenv:Header/>
  <soapenv:Body>
    {body_inner.format(token=token, sign=sign)}
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        resp    = self._session.post(self.url, data=soap.encode("utf-8"), headers=headers, timeout=30)
        if not resp.ok:
            print(f"STATUS: {resp.status_code}")
            print(f"RESPONSE: {resp.text[:500]}")
            resp.raise_for_status()
        root = etree.fromstring(resp.content)
        return root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")

    # ── dummy ──────────────────────────────────────────────────────────────────

    def dummy(self) -> dict:
        """Verifica disponibilidad del servicio."""
        resp_body = self._call('<a5:dummy xmlns:a5="http://a5.soap.ws.server.puc.sr/"/>')
        result    = resp_body.find(".//{http://a5.soap.ws.server.puc.sr/}dummyReturn")
        if result is None:
            return {"raw": etree.tostring(resp_body, pretty_print=True).decode()}
        return {
            "appserver":  result.findtext("appserver"),
            "dbserver":   result.findtext("dbserver"),
            "authserver": result.findtext("authserver"),
        }

    # ── getPersona ─────────────────────────────────────────────────────────────

    def get_persona(self, cuit: int) -> dict:
        """
        Consulta la constancia de inscripción de un contribuyente.

        Args:
            cuit: CUIT numérico (sin guiones), ej: 20123456789

        Returns:
            dict con datosGenerales, datosRegimenGeneral, datosMonotributo, etc.
        """
        cuit_int   = int(str(cuit).replace("-", "").replace(".", ""))
        body_inner = f"""<a5:getPersona_v2 xmlns:a5="http://a5.soap.ws.server.puc.sr/">
                  <token>{{token}}</token>
                  <sign>{{sign}}</sign>
                  <cuitRepresentada>{cuit_int}</cuitRepresentada>
                  <idPersona>{cuit_int}</idPersona>
                </a5:getPersona_v2>"""

        resp_body = self._call(body_inner)
        return _parse_persona(resp_body)

    def get_personas(self, cuits: list[int]) -> list[dict]:
        """Consulta múltiples CUITs."""
        return [self.get_persona(c) for c in cuits]


# ── Parser XML → dict ──────────────────────────────────────────────────────────

def _xml_to_dict(element: etree._Element) -> dict | str:
    if len(element) == 0:
        return element.text or ""

    result: dict = {}
    for child in element:
        tag   = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        value = _xml_to_dict(child)
        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(value)
        else:
            result[tag] = value
    return result


def _parse_persona(body: etree._Element) -> dict:
    fault = body.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        code    = fault.findtext("faultcode") or ""
        message = fault.findtext("faultstring") or ""
        raise RuntimeError(f"SOAP Fault [{code}]: {message}")

    persona_return = body.find(".//{http://a5.soap.ws.server.puc.sr/}personaReturn")
    if persona_return is None:
        return _xml_to_dict(body)
    return _xml_to_dict(persona_return)