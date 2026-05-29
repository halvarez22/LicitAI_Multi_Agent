"""Hidratación del payload del ComplianceGate (generation_only / sesión reanudada)."""

from app.agents.orchestrator import (
    _build_compliance_gate_payload,
    _compliance_list_from_session,
    _session_has_compliance_evidence,
)


def test_compliance_list_from_session_master_list():
    state = {
        "compliance_master_list": {
            "administrativo": [{"id": "a1"}],
            "tecnico": [],
            "formatos": [],
        }
    }
    assert _compliance_list_from_session(state)["administrativo"][0]["id"] == "a1"


def test_go_no_go_alone_is_not_compliance_evidence():
    state = {"go_no_go_result": {"semaforo": "GREEN"}, "tasks_completed": []}
    assert _session_has_compliance_evidence(state) is False


def test_gate_payload_hydrates_compliance_from_session():
    session = {
        "compliance_master_list": {
            "administrativo": [{"id": "AD-1"}],
            "tecnico": [{"id": "TE-1"}],
            "formatos": [],
        }
    }
    execution_results = {"compliance": {"status": "resumed", "data": {}}}
    payload = _build_compliance_gate_payload("sid", execution_results, session)
    comp = payload["compliance"]["data"]
    assert len(comp.get("administrativo") or []) == 1
    assert len(comp.get("tecnico") or []) == 1
