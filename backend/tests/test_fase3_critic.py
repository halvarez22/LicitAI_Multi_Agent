"""
tests/test_fase3_critic.py
Pruebas para la capa de reflexión (CriticAgent).
"""
import pytest
from app.agents.critic import CriticAgent
from app.agents.validator import ValidationReport, Conflict

def test_critic_accepts_consistent_report():
    critic = CriticAgent()
    report = ValidationReport(consistent=True, conflicts=[])
    verdict = critic.decide(report, current_iteration=0)
    assert verdict.verdict == "accept"

def test_critic_rerun_compliance_on_missing_coverage():
    critic = CriticAgent()
    report = ValidationReport(
        consistent=False, 
        conflicts=[Conflict(type="missing_coverage", description="test")],
        requires_compliance_revision=True
    )
    verdict = critic.decide(report, current_iteration=0)
    assert verdict.verdict == "rerun_compliance"

def test_critic_escalates_to_human_after_max_iterations():
    critic = CriticAgent()
    report = ValidationReport(
        consistent=False, 
        conflicts=[Conflict(type="missing_coverage", description="still missing")],
        requires_compliance_revision=True
    )
    # Iteración 2 alcanzada (límite por defecto es 2)
    verdict = critic.decide(report, current_iteration=2, max_iterations=2)
    assert verdict.verdict == "escalate_human"
    assert "MAX_ITERATIONS_REACHED" in verdict.reason_codes
