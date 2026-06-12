"""
scripts/arca — Módulos de integración con webservices de ARCA (ex AFIP)
"""
from .wsaa import get_ticket
from .constancia import ConsultaConstancia
from .padron_a13 import PadronA13

__all__ = ["get_ticket", "ConsultaConstancia", "PadronA13"]