"""Inferencia de compliance para generation_only en sesiones con dictamen previo."""
from app.agents.orchestrator import (
    _collect_completed_stages_from_session,
    _session_has_compliance_evidence,
)


def test_go_no_go_alone_does_not_infer_compliance():
    state = {"go_no_go_result": {"status": "yellow"}, "tasks_completed": []}
    assert _session_has_compliance_evidence(state) is False


def test_compliance_evidence_from_master_list():
    state = {
        "go_no_go_result": {"status": "yellow"},
        "compliance_master_list": {"administrativo": [{"id": "a1"}], "tecnico": [], "formatos": []},
    }
    assert _session_has_compliance_evidence(state) is True


def test_collect_stages_from_tasks():
    state = {
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {}},
            {"task": "stage_completed:compliance", "result": {}},
        ]
    }
    assert _collect_completed_stages_from_session(state) == {"analysis", "compliance"}
