"""Reglas deterministas de descalificación (Numeral 12.1).

Este módulo define el registro canónico de reglas para `ComplianceGate`.
Las validaciones concretas viven en `app.agents.compliance_gate` para mantener
el motor de evaluación en un solo punto.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class DisqualificationRule:
    """Describe una regla de descalificación 12.1."""

    code: str
    description: str
    regex_pattern: Optional[str]
    validation_fn: Optional[Callable[[Dict[str, Any]], bool]]
    evidence_path: str
    is_deterministic: bool = True


def get_disqualification_rules() -> List[DisqualificationRule]:
    """Regresa las 18 reglas del numeral 12.1 (A..R)."""
    return [
        DisqualificationRule("12.1.A", "Incumplimiento de requisitos de bases.", None, None, "compliance.data"),
        DisqualificationRule("12.1.B", "Acuerdo para elevar precios o colusión.", r"(?i)acuerdo.*precio.*elevar|colusi[oó]n", None, "analysis.data.requisitos_participacion"),
        DisqualificationRule("12.1.C", "Presentar propuesta en moneda distinta a MXN.", None, None, "economic.data.currency"),
        DisqualificationRule("12.1.D", "Presentar propuesta en idioma distinto al español.", None, None, "analysis.data.propuesta.idioma"),
        DisqualificationRule("12.1.E", "Documentación alterada, tachada o enmendada.", r"(?i)tachad|enmend|raspadur|alterad", None, "compliance.data"),
        DisqualificationRule("12.1.F", "No acreditar capacidad técnica suficiente.", None, None, "compliance.data"),
        DisqualificationRule("12.1.G", "Supuestos de inhabilitación legal aplicables.", None, None, "analysis.data.requisitos_participacion"),
        DisqualificationRule("12.1.H", "Omisión de la frase 'bajo protesta de decir verdad'.", r"(?i)bajo\\s+protesta\\s+de\\s+decir\\s+verdad", None, "analysis.data.requisitos_participacion"),
        DisqualificationRule("12.1.I", "Violación legal externa (validación manual).", None, None, "analysis.data"),
        DisqualificationRule("12.1.J", "Falta de firma o identificación.", r"(?i)sin firma|falta de firma|sin identificaci[oó]n", None, "compliance.data"),
        DisqualificationRule("12.1.K", "Formatos obligatorios no requisitados.", None, None, "compliance.data.formatos"),
        DisqualificationRule("12.1.L", "Información falsa (requiere verificación externa).", None, None, "analysis.data"),
        DisqualificationRule("12.1.M", "Determinación de Contraloría/SFP (fuente externa).", None, None, "analysis.data"),
        DisqualificationRule("12.1.N", "Múltiples propuestas por la misma partida.", None, None, "economic.data.items"),
        DisqualificationRule("12.1.O", "Proveedor inhabilitado por SFP.", None, None, "analysis.data"),
        DisqualificationRule("12.1.P", "Propuesta no apegada a bases.", None, None, "compliance.data"),
        DisqualificationRule("12.1.Q", "Precio desproporcionado.", None, None, "economic.data.validation_result"),
        DisqualificationRule("12.1.R", "No entrega de muestras con 24h de anticipación.", None, None, "analysis.data"),
    ]
