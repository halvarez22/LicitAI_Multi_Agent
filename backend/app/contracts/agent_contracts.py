"""
agent_contracts.py — Fase 0 Hardening
Contratos estrictos de entrada/salida para agentes LicitAI.

Feature flag: LICITAI_STRICT_CONTRACTS (default: False — backward compatible).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class AgentStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"
    FAIL = "fail"
    WAITING_FOR_DATA = "waiting_for_data"


class AgentInput(BaseModel):
    """
    Contrato de entrada estricto para cualquier agente.
    Reemplaza Dict[str, Any] en boundaries críticas.
    """
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    session_id: str = Field(..., min_length=1, description="ID único de la sesión de licitación")
    company_id: Optional[str] = Field(None, description="ID de la empresa participante")
    company_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Perfil y metadatos de la empresa"
    )
    mode: str = Field(
        default="full",
        description="Modo de operación del pipeline"
    )
    resume_generation: bool = Field(
        default=False,
        description="Indica si se debe resumir la generación pendiente"
    )
    correlation_id: Optional[str] = Field(
        None,
        description="ID de correlación para trazabilidad entre agentes"
    )
    refinement: Optional[Dict[str, Any]] = Field(
        None,
        description="Datos de refinamiento para backtracking (Fase 3)"
    )
    job_id: Optional[str] = Field(
        None,
        description="ID del Job asíncrono para reporte de progreso"
    )

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = {"full", "analysis_only", "generation", "generation_only"}
        if v not in valid:
            raise ValueError(f"Modo inválido '{v}'. Válidos: {sorted(valid)}")
        return v


class AgentOutput(BaseModel):
    """
    Contrato de salida estricto para cualquier agente.
    Garantiza que el orchestrator siempre pueda leer .status sin try/except.
    """
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    status: AgentStatus
    agent_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    data: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None
    error: Optional[str] = None
    confidence_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Score de confianza agregado [0-1]. Reservado para Fase 1."
    )
    processing_time_sec: Optional[float] = Field(
        None,
        ge=0.0,
        description="Duración de procesamiento en segundos"
    )
    correlation_id: Optional[str] = None

    @model_validator(mode="after")
    def error_requires_message(self) -> "AgentOutput":
        if self.status == AgentStatus.ERROR and not self.error and not self.message:
            raise ValueError("Un AgentOutput con status=error debe incluir 'error' o 'message'")
        return self

    def to_legacy_dict(self) -> Dict[str, Any]:
        """
        Serializa al formato dict legacy que usa el pipeline actual.
        Garantiza backward compatibility durante la migración.
        """
        out: Dict[str, Any] = {
            "status": self.status.value,
            "agent": self.agent_id,
            "data": self.data,
        }
        if self.message:
            out["message"] = self.message
        if self.error:
            out["error"] = self.error
        return out
