"""Esquema tipado para datos dinámicos de plantillas legales."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LegalTemplateData:
    """Campos mínimos para render de anexos legales bloqueados."""

    razon_social: str
    rfc: str
    numero_licitacion: str
    servicio: str
    nombre_representante: str
    lugar: str
    fecha: str
    tipo_licitacion: str = "Licitacion Publica"
    autoridad_convocante: str = "Convocante"
