"""
scripts/arca — Módulos de integración con webservices de ARCA (ex AFIP)
"""
from .wsaa import get_ticket
from .constancia import ConsultaConstancia

__all__ = ["get_ticket", "ConsultaConstancia"]