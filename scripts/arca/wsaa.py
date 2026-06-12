"""
wsaa.py — Autenticación ARCA (WSAA)
Obtiene el Ticket de Acceso (token + sign) para un servicio dado.
Cachea el ticket en disco y lo renueva solo cuando expira.

Variables de entorno:
    ARCA_CERT       ruta a .crt  O  contenido PEM directo
    ARCA_KEY        ruta a .key  O  contenido PEM directo
    ARCA_PROD       "1" = producción, "0" / ausente = homologación
    ARCA_CACHE_DIR  carpeta de caché (default: temp/arca_tickets)
"""

import os
import base64
import datetime
import pickle
import subprocess
import tempfile
from pathlib import Path

import requests
from lxml import etree

# ── Endpoints ──────────────────────────────────────────────────────────────────
WSAA_URL_HOMO = "https://wsaahomo.afip.gov.ar/ws/services/LoginCms"
WSAA_URL_PROD = "https://wsaa.afip.gov.ar/ws/services/LoginCms"

CACHE_DIR = Path(os.getenv("ARCA_CACHE_DIR", tempfile.gettempdir())) / "arca_tickets"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TTL_MINUTES = 720  # 12 horas — ARCA exige menos de 24hs


# ── Helpers cert/key ───────────────────────────────────────────────────────────

def _resolver_pem(valor: str, sufijo: str) -> str:
    """Ruta a archivo o contenido PEM directo → siempre devuelve ruta."""
    if valor and Path(valor).exists():
        return valor
    tmp = Path(tempfile.mktemp(suffix=sufijo, dir=tempfile.gettempdir()))
    tmp.write_text(valor)
    try:
        tmp.chmod(0o600)
    except Exception:
        pass
    return str(tmp)


def _get_cert_key_paths(cert: str, key: str) -> tuple[str, str]:
    return _resolver_pem(cert, ".crt"), _resolver_pem(key, ".key")


# ── TRA ────────────────────────────────────────────────────────────────────────

def _build_tra(service: str) -> bytes:
    now      = datetime.datetime.now(datetime.timezone.utc)
    gen_time = (now - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    exp_time = (now + datetime.timedelta(minutes=TTL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    unique_id = abs(hash(f"{service}{now.timestamp()}")) % (10**10)

    tra_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<loginTicketRequest version="1.0">
  <header>
    <uniqueId>{unique_id}</uniqueId>
    <generationTime>{gen_time}</generationTime>
    <expirationTime>{exp_time}</expirationTime>
  </header>
  <service>{service}</service>
</loginTicketRequest>"""
    return tra_xml.encode("utf-8")


# ── Firma ──────────────────────────────────────────────────────────────────────
def _sign_tra(tra_bytes: bytes, cert_path: str, key_path: str) -> str:
    """Firma el TRA usando oscrypto con SHA1. Devuelve base64 del CMS."""
    from oscrypto import asymmetric
    from oscrypto.keys import parse_certificate, parse_private
    from asn1crypto import cms, core, algos, x509, pem as asn1pem
    import hashlib

    cert_pem = Path(cert_path).read_bytes()
    key_pem  = Path(key_path).read_bytes()

    cert_obj  = asymmetric.load_certificate(cert_pem)
    key_obj   = asymmetric.load_private_key(key_pem)
    signature = asymmetric.rsa_pkcs1v15_sign(key_obj, tra_bytes, "sha1")

    # Construir CMS SignedData manualmente con asn1crypto
    digest    = hashlib.sha1(tra_bytes).digest()

    signed_data = cms.SignedData({
        'version': 'v1',
        'digest_algorithms': [{'algorithm': 'sha1'}],
        'encap_content_info': {
            'content_type': 'data',
            'content': tra_bytes,
        },
        'certificates': [cert_obj.asn1],
        'signer_infos': [{
            'version': 'v1',
            'sid': cms.SignerIdentifier(
                name='issuer_and_serial_number',
                value={
                    'issuer': cert_obj.asn1['tbs_certificate']['issuer'],
                    'serial_number': cert_obj.asn1['tbs_certificate']['serial_number'],
                }
            ),
            'digest_algorithm': {'algorithm': 'sha1'},
            'signature_algorithm': {'algorithm': 'rsassa_pkcs1v15'},
            'signature': signature,
        }],
    })

    content_info = cms.ContentInfo({
        'content_type': 'signed_data',
        'content': signed_data,
    })

    return base64.b64encode(content_info.dump()).decode()


# ── WSAA ───────────────────────────────────────────────────────────────────────

def _call_wsaa(cms_b64: str, prod: bool = False) -> dict:
    url = WSAA_URL_PROD if prod else WSAA_URL_HOMO

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov.ar">
  <soapenv:Header/>
  <soapenv:Body>
    <wsaa:loginCms>
      <wsaa:in0>{cms_b64}</wsaa:in0>
    </wsaa:loginCms>
  </soapenv:Body>
</soapenv:Envelope>"""

    headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
    resp    = requests.post(url, data=soap_body.encode("utf-8"), headers=headers, timeout=30)

    if not resp.ok:
        raise RuntimeError(f"WSAA error {resp.status_code}:\n{resp.text}")

    root = etree.fromstring(resp.content)
    body = root.find(".//{http://wsaa.view.sua.dvadac.desein.afip.gov.ar}loginCmsReturn")
    if body is None:
        raise ValueError(f"Respuesta WSAA inesperada:\n{resp.text}")

    ta_xml  = body.text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    ta_root = etree.fromstring(ta_xml.encode("utf-8"))
    token   = ta_root.findtext(".//token")
    sign    = ta_root.findtext(".//sign")
    exp_str = ta_root.findtext(".//expirationTime")
    exp_dt  = datetime.datetime.fromisoformat(exp_str)

    return {"token": token, "sign": sign, "expiration": exp_dt}


# ── API pública ────────────────────────────────────────────────────────────────

def get_ticket(
    service: str,
    cert_path: str = None,
    key_path: str = None,
    prod: bool = None,
) -> dict:
    """
    Retorna el ticket de acceso para *service*, usando caché en disco.

    Args:
        service:   ID del servicio ARCA, ej: 'ws_sr_constancia_inscripcion'
        cert_path: Ruta al .crt  O  contenido PEM  (default: env ARCA_CERT)
        key_path:  Ruta al .key  O  contenido PEM  (default: env ARCA_KEY)
        prod:      True = producción  (default: env ARCA_PROD == "1")

    Returns:
        dict con 'token', 'sign', 'expiration'
    """
    cert_raw = cert_path or os.environ["ARCA_CERT"]
    key_raw  = key_path  or os.environ["ARCA_KEY"]
    if prod is None:
        prod = os.getenv("ARCA_PROD", "0") == "1"

    cert_file, key_file = _get_cert_key_paths(cert_raw, key_raw)

    cache_file = CACHE_DIR / f"{service}_{'prod' if prod else 'homo'}.pkl"

    # Verificar caché
    if cache_file.exists():
        try:
            cached = pickle.loads(cache_file.read_bytes())
            now    = datetime.datetime.now(datetime.timezone.utc)
            if cached["expiration"] > now + datetime.timedelta(minutes=5):
                return cached
        except Exception:
            pass

    # Generar nuevo ticket
    tra    = _build_tra(service)
    cms    = _sign_tra(tra, cert_file, key_file)
    ticket = _call_wsaa(cms, prod=prod)

    cache_file.write_bytes(pickle.dumps(ticket))
    return ticket