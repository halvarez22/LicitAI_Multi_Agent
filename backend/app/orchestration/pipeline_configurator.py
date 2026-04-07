"""
pipeline_configurator.py — Fase 2 Orquestador Adaptativo
Define la configuración dinámica del pipeline según la complejidad del documento.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class PipelineType(str, Enum):
    DEFAULT_FULL = "default_full"
    ANALYSIS_LIGHT = "analysis_light"
    COST_FOCUS = "cost_focus"


class ActionType(str, Enum):
    CONTINUE = "continue"
    SKIP_STAGE = "skip_stage"
    STOP = "stop"
    ESCALATE = "escalate"


class ConditionType(str, Enum):
    LOW_CONFIDENCE_AVG = "low_confidence_avg"
    TOO_MANY_LOW_CONF_ITEMS = "too_many_low_conf_items"
    MISSING_CRITICAL_DATA = "missing_critical_data"


class ShortCircuitRule(BaseModel):
    """
    Regla de decisión rápida para el pipeline.
    """
    name: str
    condition_type: ConditionType
    threshold: float | int
    action: ActionType
    target_stage: Optional[str] = None


class PipelineConfig(BaseModel):
    """
    Representación del plan de ejecución adaptativo.
    """
    pipeline_type: PipelineType
    stages: List[str]
    short_circuit_rules: List[ShortCircuitRule] = Field(default_factory=list)


class PipelineConfigurator:
    """
    Genera la configuración óptima para una ejecución de pipeline.
    """

    @staticmethod
    def configure(
        document_profile: Dict[str, Any],
        mode: str = "full",
        confidence_summary: Optional[Dict[str, Any]] = None
    ) -> PipelineConfig:
        """
        Determina la ruta de ejecución óptima basada en el perfil del documento.
        """
        complexity = document_profile.get("complexity", "medium")
        is_cost_focus = document_profile.get("is_cost_focus", False)
        
        # ── 1. Determinar Tipo de Pipeline ───────────────────
        if mode == "analysis_only":
            p_type = PipelineType.DEFAULT_FULL
            # Incluye economic para usar session_line_items + catálogo en la misma pasada que "Analizar bases" (UI).
            default_stages = ["analysis", "compliance", "economic"]
        elif mode in ["generation_only", "generation"]:
            p_type = PipelineType.DEFAULT_FULL
            default_stages = [
                "analysis", "compliance", "economic", 
                "datagap", "technical", "formats", 
                "economic_writer", "packager", "delivery"
            ]
        elif complexity == "low" and not is_cost_focus:
            p_type = PipelineType.ANALYSIS_LIGHT
            default_stages = ["analysis", "compliance", "formats", "packager", "delivery"]
        elif is_cost_focus:
            p_type = PipelineType.COST_FOCUS
            default_stages = ["analysis", "compliance", "economic", "economic_writer", "packager", "delivery"]
        else:
            p_type = PipelineType.DEFAULT_FULL
            default_stages = [
                "analysis", "compliance", "economic", 
                "datagap", "technical", "formats", 
                "economic_writer", "packager", "delivery"
            ]

        # ── 2. Definir Reglas de Short-Circuit ────────────────
        rules = [
            ShortCircuitRule(
                name="Stop on missing critical data",
                condition_type=ConditionType.MISSING_CRITICAL_DATA,
                threshold=1,
                action=ActionType.STOP
            )
        ]

        if confidence_summary:
            rules.append(ShortCircuitRule(
                name="Escalate on low avg confidence",
                condition_type=ConditionType.LOW_CONFIDENCE_AVG,
                threshold=0.6, # Ejemplo
                action=ActionType.ESCALATE
            ))

        return PipelineConfig(
            pipeline_type=p_type,
            stages=default_stages,
            short_circuit_rules=rules
        )
