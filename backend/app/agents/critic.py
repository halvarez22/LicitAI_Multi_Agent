"""
critic.py — Fase 3 Backtracking
Capa de reflexión determinística (MVP) para decidir rumbos de refinamiento.
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.agents.validator import ValidationReport


class CriticVerdict(BaseModel):
    verdict: Literal["accept", "rerun_analyst", "rerun_compliance", "escalate_human"]
    reason_codes: List[str] = []
    max_additional_llm_calls: int = 0


class CriticAgent:
    """
    Decide si un reporte de validación requiere reabrir el pipeline (backtracking).
    """

    def decide(self, report: ValidationReport, current_iteration: int, max_iterations: int = 2) -> CriticVerdict:
        # Lógica priorizada
        if report.consistent:
            return CriticVerdict(verdict="accept")
            
        # Si ya se alcanzó el límite, escalar a humano
        if current_iteration >= max_iterations:
            return CriticVerdict(
                verdict="escalate_human",
                reason_codes=["MAX_ITERATIONS_REACHED", "RESIDUAL_CONFLICTS"]
            )
            
        # Priorizar rumbos de corrección
        # Si hay muchos conflictos de cobertura, pedir revisión a Compliance (Master List)
        if report.requires_compliance_revision:
            return CriticVerdict(
                verdict="rerun_compliance",
                reason_codes=["MISSING_COVERAGE"],
                max_additional_llm_calls=1
            )
            
        if report.requires_analyst_revision:
             return CriticVerdict(
                verdict="rerun_analyst",
                reason_codes=["LOW_CONFIDENCE"],
                max_additional_llm_calls=1
            )
            
        # Fallback por defecto si no es consistente
        return CriticVerdict(
            verdict="accept",
            reason_codes=["NON_CRITICAL_CONFLICTS"]
        )
