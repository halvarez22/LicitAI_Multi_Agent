from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TipoJunta(str, Enum):
    PRIMERA = "primera"
    SEGUNDA = "segunda"


class PostClarificationContextModel(BaseModel):
    """Bloque persistido en sesión bajo clave `post_clarification_context`."""

    acta_id: Optional[str] = None
    tipo_junta: TipoJunta = TipoJunta.PRIMERA
    archivo_original: str = ""
    texto_extraido: Optional[str] = None
    confianza_extraccion: float = 0.0
    preguntas_aclaracion: List[Dict[str, Any]] = Field(default_factory=list)
    carta_33_bis_draft: Optional[str] = None
    carta_33_bis_docx_path: Optional[str] = None
    estado: str = "pendiente"  # pendiente | extraida | borrador_listo | revisada
    extraido_por: Optional[str] = None
    ultima_actualizacion: datetime = Field(default_factory=datetime.utcnow)


class PostClarificationActaRequest(BaseModel):
    """Entrada del endpoint POST /post-clarification/acta."""

    document_id: str
    tipo_junta: TipoJunta = TipoJunta.PRIMERA


class GenerateCarta33BisRequest(BaseModel):
    """Entrada del endpoint para generar o regenerar carta art. 33 Bis."""

    force_regenerate: bool = False
