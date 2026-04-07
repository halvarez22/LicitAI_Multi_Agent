"""Servicios de post-aclaraciones (actas + carta art. 33 Bis)."""

from app.post_clarification.models import (
    GenerateCarta33BisRequest,
    PostClarificationActaRequest,
    PostClarificationContextModel,
    TipoJunta,
)
from app.post_clarification.service import (
    generate_carta_33_bis,
    get_post_clarification_context,
    process_acta_document,
)

__all__ = [
    "GenerateCarta33BisRequest",
    "PostClarificationActaRequest",
    "PostClarificationContextModel",
    "TipoJunta",
    "generate_carta_33_bis",
    "get_post_clarification_context",
    "process_acta_document",
]
