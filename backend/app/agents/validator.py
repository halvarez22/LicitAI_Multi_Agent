"""
validator.py — Fase 3 Backtracking
Agente de validación cruzada determinística entre resultados de Analyst y Compliance.
"""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.contracts.agent_contracts import AgentOutput, AgentStatus


class Conflict(BaseModel):
    id_req: Optional[str] = None
    type: Literal["missing_coverage", "id_mismatch", "contradiction_hint"]
    description: str


class ValidationReport(BaseModel):
    consistent: bool
    conflicts: List[Conflict] = []
    requires_analyst_revision: bool = False
    requires_compliance_revision: bool = False
    suggested_corrections: Dict[str, str] = {}


class ValidatorAgent:
    """
    Realiza validación cruzada sin LLM (determinístico) entre Analyst y Compliance.
    """

    def validate(self, analyst_out: AgentOutput, compliance_out: AgentOutput) -> ValidationReport:
        conflicts = []
        requires_analyst = False
        requires_compliance = False
        
        # 1. Extraer datos (extraer a diccionarios si son AgentOutput)
        analyst_data = analyst_out.data if hasattr(analyst_out, 'data') else {}
        compliance_data = compliance_out.data if hasattr(compliance_out, 'data') else {}
        
        # 2. Check Cobertura (Analyst IDs -> Compliance master list)
        # Por simplicidad, asumimos que Compliance reporta 'administrativo', 'tecnico', etc.
        comp_items = []
        for cat in ["administrativo", "tecnico", "formatos"]:
            comp_items.extend(compliance_data.get(cat, []))
        
        # IDs reportados por Compliance
        comp_ids = set()
        for c in comp_items:
            rid = str(c.get("id", "")).strip().lower()
            if rid: comp_ids.add(rid)

        # Requisitos analizados por Analyst
        analyst_reqs = analyst_data.get("requirements", [])
        for req in analyst_reqs:
            rid = str(req.get("id", "")).strip().lower()
            if rid and rid not in comp_ids:
                conflicts.append(Conflict(
                    id_req=rid,
                    type="missing_coverage",
                    description=f"Requisito '{rid}' analizado por Analyst no existe en Master List de Compliance."
                ))
                requires_compliance = True
        
        # 3. Check Confidence (Enlace con Fase 1 opcional)
        # Si Analyst tiene un score de confianza bajísimo (< 0.40), pedir revisión.
        if (analyst_out.confidence_score or 1.0) < 0.40:
             conflicts.append(Conflict(
                type="contradiction_hint",
                description="Baja confianza crítica en Analyst detectada por Validator."
            ))
             requires_analyst = True

        consistent = len(conflicts) == 0
        suggested_corrections = {}
        for c in conflicts:
            if c.id_req:
                suggested_corrections[c.id_req] = c.description

        return ValidationReport(
            consistent=consistent,
            conflicts=conflicts,
            requires_analyst_revision=requires_analyst,
            requires_compliance_revision=requires_compliance,
            suggested_corrections=suggested_corrections
        )
