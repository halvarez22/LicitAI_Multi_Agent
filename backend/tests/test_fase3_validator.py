"""
tests/test_fase3_validator.py
Pruebas para el motor de validación cruzada determinística.
"""
import pytest
from app.agents.validator import ValidatorAgent
from app.contracts.agent_contracts import AgentOutput, AgentStatus

def test_validator_detects_missing_coverage():
    # Analyst analizó un requisito 'REQ-1'
    analyst_out = AgentOutput(
        status=AgentStatus.SUCCESS, agent_id="a", session_id="s",
        data={"requirements": [{"id": "REQ-1"}]}
    )
    # Compliance NO tiene 'REQ-1' en su lista técnica
    compliance_out = AgentOutput(
        status=AgentStatus.SUCCESS, agent_id="c", session_id="s",
        data={"tecnico": [{"id": "REQ-2"}]}
    )
    
    validator = ValidatorAgent()
    report = validator.validate(analyst_out, compliance_out)
    
    assert report.consistent is False
    assert any(c.type == "missing_coverage" for c in report.conflicts)
    assert report.requires_compliance_revision is True

def test_validator_consistent_on_empty_matching_lists():
    analyst_out = AgentOutput(
        status=AgentStatus.SUCCESS, agent_id="a", session_id="s",
        data={"requirements": []}
    )
    compliance_out = AgentOutput(
        status=AgentStatus.SUCCESS, agent_id="c", session_id="s",
        data={"administrativo": []}
    )
    
    validator = ValidatorAgent()
    report = validator.validate(analyst_out, compliance_out)
    assert report.consistent is True
    assert len(report.conflicts) == 0
