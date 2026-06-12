"""
padron_a13.py — Consulta de Padrón Alcance 13 (ws_sr_padron_a13)
ARCA — ex AFIP

Permite consultar datos públicos de cualquier CUIT sin ser su representante.
"""

import os
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from lxml import etree
import requests

from .wsaa import get_ticket

urllib3.disable_warnings()

URL_HOMO   = "https://awshomo.afip.gov.ar/sr-padron/webservices/personaServiceA13"
URL_PROD   = "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13"
SERVICE_ID = "ws_sr_padron_a13"
NS         = "http://a13.soap.ws.server.puc.sr/"


class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers="DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _make_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", LegacySSLAdapter())
    return session


class PadronA13:
    """Cliente para ws_sr_padron_a13. Consulta cualquier CUIT sin ser representante."""

    def __init__(self, cert_path=None, key_path=None, prod=None):
        self.cert_path = cert_path or os.environ["ARCA_CERT"]
        self.key_path  = key_path  or os.environ["ARCA_KEY"]
        if prod is None:
            prod = os.getenv("ARCA_PROD", "0") == "1"
        self.prod     = prod
        self.url      = URL_PROD if prod else URL_HOMO
        self.cuit_rep = os.getenv("ARCA_CUIT", "20120344111")
        self._session = _make_session()
        self._ticket  = None

    def _get_auth(self):
        self._ticket = get_ticket(
            SERVICE_ID,
            cert_path=self.cert_path,
            key_path=self.key_path,
            prod=self.prod,
        )
        return self._ticket["token"], self._ticket["sign"]

    def _call(self, body_inner):
        token, sign = self._get_auth()
        soap = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:a13="{NS}">
  <soapenv:Header/>
  <soapenv:Body>
    {body_inner.format(token=token, sign=sign, cuit_rep=self.cuit_rep)}
  </soapenv:Body>
</soapenv:Envelope>"""

        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        resp    = self._session.post(self.url, data=soap.encode("utf-8"), headers=headers, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"A13 error {resp.status_code}:\n{resp.text}")
        root = etree.fromstring(resp.content)
        return root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Body")

    def dummy(self):
        resp_body = self._call(f'<a13:dummy xmlns:a13="{NS}"/>')
        result    = resp_body.find(f".//{{{NS}}}return")
        if result is None:
            return {"raw": etree.tostring(resp_body, pretty_print=True).decode()}
        return {
            "appserver":  result.findtext("appserver"),
            "dbserver":   result.findtext("dbserver"),
            "authserver": result.findtext("authserver"),
        }

    def get_persona(self, cuit):
        cuit_int   = int(float(str(cuit).replace("-", "")))
        body_inner = f"""<a13:getPersona xmlns:a13="{NS}">
          <token>{{token}}</token>
          <sign>{{sign}}</sign>
          <cuitRepresentada>{{cuit_rep}}</cuitRepresentada>
          <idPersona>{cuit_int}</idPersona>
        </a13:getPersona>"""
        resp_body = self._call(body_inner)
        return _parse_persona(resp_body)

    def get_personas(self, cuits):
        return [self.get_persona(c) for c in cuits]


def _xml_to_dict(element):
    if len(element) == 0:
        return element.text or ""
    result = {}
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


def _parse_persona(body):
    fault = body.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        code    = fault.findtext("faultcode") or ""
        message = fault.findtext("faultstring") or ""
        raise RuntimeError(f"SOAP Fault [{code}]: {message}")

    persona_return = body.find(".//personaReturn")
    if persona_return is None:
        return _xml_to_dict(body)

    result  = _xml_to_dict(persona_return)
    persona = result.get("persona", {})
    persona["metadata"] = result.get("metadata", {})
    return persona