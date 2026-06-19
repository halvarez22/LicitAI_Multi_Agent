"""Tests del coordinador de intake autónomo (Semana 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.autonomous_intake_coordinator import (
    SCHEMA_VERSION,
    build_autonomous_intake_state,
    consolidate_pending_from_intake_plan,
    run_post_analysis_checkpoint,
)
from app.services.hitl_queue_service import semantic_question_fingerprint


def _dup_question(qid: str, field_target: str, label: str) -> dict:
    return {
        "question_id": qid,
        "type": "intake_planner",
        "field_target": field_target,
        "label": label,
        "question": f"¿Cuál es tu {label}?",
        "blocking": True,
    }


def test_consolidate_does_not_duplicate_semantic_pending():
    """HRU: la misma pregunta en intake_plan y pending_questions no duplica la cola."""
    q = _dup_question("INTAKE-B-001", "solvencia_economica.capital", "Capital contable")
    q_dup = dict(q)
    q_dup["question_id"] = "INTAKE-B-001-ALT"

    session = {
        "pending_questions": [q],
        "intake_plan": {"questions": [q_dup], "checklist_corporativo": []},
        "triage_context": {"tender_category": "obra_publica", "law": "LOPSRM"},
    }
    merged, dedupe_removed, sources = consolidate_pending_from_intake_plan(session)

    fps = [semantic_question_fingerprint(x) for x in merged]
    assert len(fps) == len(set(fps))
    assert len(merged) == 1
    assert dedupe_removed >= 0
    assert "intake_plan" in sources
    assert "pending_questions" in sources


def test_consolidate_purges_corporate_checklist_from_queue():
    corp = _dup_question("INTAKE-CORP-01", "solvencia_legal.rfc", "RFC")
    chat_q = _dup_question("INTAKE-B-002", "solvencia_economica.anos", "Años de experiencia")

    session = {
        "pending_questions": [corp, chat_q],
        "intake_plan": {
            "questions": [],
            "checklist_corporativo": [corp],
        },
    }
    merged, _, _ = consolidate_pending_from_intake_plan(session)
    keys = {str(q.get("question_id")) for q in merged}
    assert "INTAKE-CORP-01" not in keys
    assert "INTAKE-B-002" in keys


def test_build_autonomous_intake_state_respects_triage():
    session = {
        "triage_context": {"tender_category": "servicios", "law": "LAASSP", "procedure_type": "LP"},
    }
    block = build_autonomous_intake_state(
        session_state=session,
        mode="analysis_only",
        merged_pending=[{"blocking": True}],
        dedupe_removed=2,
        sources_merged=["intake_plan"],
    )
    assert block["version"] == SCHEMA_VERSION
    assert block["triage"]["tender_category"] == "servicios"
    assert block["triage"]["law"] == "LAASSP"
    assert block["queue_stats"]["total_pending"] == 1
    assert block["queue_stats"]["dedupe_removed"] == 2
    assert block["status"] == "collecting_gaps"


@pytest.mark.asyncio
async def test_run_post_analysis_checkpoint_disabled_by_default(monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.AUTONOMOUS_INTAKE_ENABLED", False)
    mem = AsyncMock()
    result = await run_post_analysis_checkpoint(mem, "sess_x", mode="analysis_only")
    assert result is None
    mem.save_session.assert_not_called()


@pytest.mark.asyncio
async def test_run_post_analysis_checkpoint_persists_when_enabled(monkeypatch):
    monkeypatch.setattr("app.config.settings.settings.AUTONOMOUS_INTAKE_ENABLED", True)
    q = _dup_question("INTAKE-B-010", "solvencia_economica.capital", "Capital contable")
    mem = AsyncMock()
    mem.get_session = AsyncMock(
        return_value={
            "pending_questions": [],
            "intake_plan": {"questions": [q], "checklist_corporativo": []},
            "triage_context": {"tender_category": "obra_publica"},
        }
    )
    mem.save_session = AsyncMock(return_value=True)

    snap = await run_post_analysis_checkpoint(mem, "sess_y", mode="full")
    assert snap is not None
    assert snap["version"] == SCHEMA_VERSION
    mem.save_session.assert_called_once()
    saved = mem.save_session.call_args[0][1]
    assert "autonomous_intake" in saved
    assert len(saved.get("pending_questions") or []) == 1
