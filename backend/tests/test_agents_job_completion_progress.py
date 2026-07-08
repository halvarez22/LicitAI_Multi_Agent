"""Tests PR2 — progreso final de jobs Redis alineado al orquestador."""

from app.api.v1.routes.agents import _job_completion_progress


def test_waiting_for_data_not_100_percent():
    prog = _job_completion_progress("waiting_for_data")
    assert prog["pct"] == 72
    assert prog["orchestrator_held"] is True
    assert prog["orchestrator_status"] == "waiting_for_data"
    assert prog["stage"] == "held"


def test_go_no_go_pending_held():
    prog = _job_completion_progress("go_no_go_pending")
    assert prog["pct"] == 72
    assert prog["orchestrator_held"] is True
    assert prog["orchestrator_status"] == "go_no_go_pending"


def test_success_completes_at_100():
    prog = _job_completion_progress("success")
    assert prog["pct"] == 100
    assert prog["orchestrator_held"] is False


def test_error_not_marked_complete():
    prog = _job_completion_progress("error")
    assert prog["pct"] == 0
    assert prog["orchestrator_held"] is False
