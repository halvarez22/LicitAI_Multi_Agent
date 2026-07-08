"""Contrato del listado unificado de preguntas para la junta de aclaraciones (convocante)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JuntaQuestionTipo(str, Enum):
    TECNICA = "tecnica"
    LEGAL = "legal"
    ECONOMICA = "economica"
    ADMINISTRATIVA = "administrativa"


class JuntaQuestionPrioridad(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


class JuntaQuestionStatus(str, Enum):
    BORRADOR = "borrador"
    APROBADA = "aprobada"
    ENVIADA = "enviada"
    EXCLUIDA = "excluida"


class JuntaQuestionSource(str, Enum):
    ANALYST_JUNTA = "analyst_junta"
    ANALYST_GAP = "analyst_gap"
    ANALYST_ALERT = "analyst_alert"
    EVIDENCE_CONFLICT = "evidence_conflict"
    MINI_DICTAMEN = "mini_dictamen"
    THEMATIC_BASES = "thematic_bases"
    GO_NO_GO = "go_no_go"
    COMPLIANCE = "compliance"


class JuntaAclaracionesQuestionItem(BaseModel):
    """Pregunta redactada para formular a la convocante en la junta."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question_id: str = Field(..., min_length=1)
    tipo: JuntaQuestionTipo = JuntaQuestionTipo.TECNICA
    prioridad: JuntaQuestionPrioridad = JuntaQuestionPrioridad.MEDIA
    status: JuntaQuestionStatus = JuntaQuestionStatus.BORRADOR
    pregunta: str = Field(..., min_length=8)
    motivo: str = Field(default="", max_length=2000)
    referencia_bases: Optional[str] = None
    archivo_fuente: Optional[str] = None
    pagina: Optional[str] = None
    source: JuntaQuestionSource
    source_ref: Optional[str] = None
    provenance_ui: Dict[str, Any] = Field(default_factory=dict)


class JuntaAclaracionesQuestionsSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: int = 0
    por_tipo: Dict[str, int] = Field(default_factory=dict)
    por_prioridad: Dict[str, int] = Field(default_factory=dict)
    por_fuente: Dict[str, int] = Field(default_factory=dict)
    listas_para_junta: int = 0
    para_convocante: int = 0


class JuntaAclaracionesQuestionsBundle(BaseModel):
    """Persistido en sesión bajo ``junta_aclaraciones_questions``."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    schema_version: str = Field(default="1.0.0", min_length=1)
    session_id: str = Field(..., min_length=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: JuntaAclaracionesQuestionsSummary = Field(
        default_factory=JuntaAclaracionesQuestionsSummary
    )
    items: List[JuntaAclaracionesQuestionItem] = Field(default_factory=list)
    excluded_contamination: int = 0
    contamination_gate_enabled: bool = True
