"""Tests del controlador de cola por modo (F2)."""

from __future__ import annotations

import pytest

from app.services.generation_queue_controller import (
    apply_generation_mode_to_jobs,
    gen_job_status,
    prepare_generation_queue_with_mode,
    set_gen_job_status,
)


@pytest.fixture(autouse=True)
def legacy_single_stream(monkeypatch):
    """Tests F2 legacy: dual-stream deshabilitado."""
    monkeypatch.setattr(
        "app.services.generation_queue_controller.dual_stream_enabled",
        lambda: False,
    )


def test_apply_technical_marks_economic_skipped():
    jobs = apply_generation_mode_to_jobs(
        [
            {"id": "technical", "status": "pending"},
            {"id": "economic_writer", "status": "pending"},
        ],
        "technical",
    )
    by_id = {j["id"]: j["status"] for j in jobs}
    assert by_id["technical"] == "pending"
    assert by_id["economic_writer"] == "skipped"


def test_prepare_queue_technical_mode():
    session = {}
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="technical",
    )
    assert state is not None
    assert state["generation_mode"] == "technical"
    assert gen_job_status(state, "economic_writer") == "skipped"
    assert gen_job_status(state, "formats") == "pending"


def test_prepare_queue_economic_mode():
    session = {}
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="economic",
    )
    assert gen_job_status(state, "datagap") == "skipped"
    assert gen_job_status(state, "economic_writer") == "pending"


def test_resume_preserves_done_and_applies_skips():
    session = {
        "generation_state": {
            "status": "running",
            "jobs": [
                {"id": "technical", "status": "done"},
                {"id": "formats", "status": "done"},
                {"id": "economic_writer", "status": "blocked"},
            ],
        }
    }
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=True,
        orchestrator_mode="generation_only",
        generation_mode="economic",
    )
    assert gen_job_status(state, "technical") == "skipped"
    assert gen_job_status(state, "economic_writer") == "blocked"
    set_gen_job_status(state, "economic_writer", "pending")
    assert gen_job_status(state, "economic_writer") == "pending"
