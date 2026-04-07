"""
orchestrator_contracts.py — Fase 0 Hardening
Schema estricto del estado del orquestador.
Elimina el dict libre 'orchestrator_decision' del pipeline actual.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class OrchestratorState(BaseModel):
    """
    Schema versionado del estado de decisión del orquestador.
    Reemplaza el dict libre 'orchestrator_decision' en la respuesta del pipeline.
    """
    model_config = {"extra": "forbid"}

    stop_reason: str = Field(
        ...,
        description=(
            "Razón de pausa o fin. Valores conocidos: "
            "FINAL_OK, ANALYSIS_COMPLETED, GENERATION_COMPLETED, COMPLIANCE_ERROR, "
            "ECONOMIC_GAP, INCOMPLETE_DATA, INVALID_MODE, INVALID_INPUT, LOW_CONFIDENCE"
        )
    )
    aggregate_health: str = Field(
        ...,
        description="Estado agregado del pipeline: 'ok' | 'partial' | 'failed'"
    )
    agent_status: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapa agent_id → status string para cada agente ejecutado"
    )
    next_steps: List[str] = Field(
        default_factory=list,
        description="Lista de hitos completados en esta ejecución"
    )
    history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Historal de tareas completadas persistido"
    )
    summary: Optional[str] = None

    # Campos reservados para Fase 2 (Adaptive Orchestrator)
    pipeline_type: Optional[str] = Field(
        None,
        description="Tipo de pipeline ejecutado (future use)"
    )
    stages_executed: Optional[int] = Field(
        None,
        ge=0,
        description="Número de stages ejecutados (future use)"
    )
    correlation_id: Optional[str] = None

    waiting_hints: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Contexto estructurado cuando el pipeline pausa por datos faltantes "
            "(p. ej. ECONOMIC_GAP: alertas de bases, resumen analista, conteo de precios faltantes)."
        ),
    )
