"""Tests P1-01: rehydrate_analysis_artifacts."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.analysis_artifacts_rehydrate_service import (
    RehydrateAnalysisArtifactsResult,
    RehydrateStepResult,
    rehydrate_analysis_artifacts,
)


def _session_with_compliance() -> dict:
    return {
        "compliance_master_list": {
            "administrativo": [{"id": "a1"}],
            "tecnico": [{"id": "t1"}],
            "formatos": [{"id": "f1"}],
        },
        "economic_user_inputs": {"fsr": 0.34, "imss": 0.34},
        "generation_state": {"status": "blocked"},
        "bases_analysis_snapshot": {"pending_reanalysis": True, "fingerprint": "abc"},
    }


@pytest.mark.asyncio
async def test_rehydrate_missing_session():
    mem = MagicMock()
    mem.get_session = AsyncMock(return_value=None)
    result = await rehydrate_analysis_artifacts(mem, "missing")
    assert result.success is False
    assert result.error == "session_not_found"


@pytest.mark.asyncio
async def test_rehydrate_missing_compliance():
    mem = MagicMock()
    mem.get_session = AsyncMock(return_value={"name": "x"})
    result = await rehydrate_analysis_artifacts(mem, "sess")
    assert result.success is False
    assert result.error == "compliance_master_list_missing"


@pytest.mark.asyncio
async def test_rehydrate_happy_path_preserves_hitl():
    state = _session_with_compliance()

    async def _get_session(sid):
        return state

    async def _save_session(sid, patch):
        if isinstance(patch, dict):
            state.update(patch)
        return True

    mem = MagicMock()
    mem.get_session = AsyncMock(side_effect=_get_session)
    mem.save_session = AsyncMock(side_effect=_save_session)
    mem.get_documents = AsyncMock(return_value=[{"filename": "bases.pdf"}])

    fake_bundle = MagicMock()
    fake_bundle.items = [{"question_id": "j1"}, {"question_id": "j2"}]

    fake_checklist = MagicMock()
    fake_checklist.hitos = [MagicMock()] * 6

    async def _ensure_candidates(mem, sid, st=None):
        state["document_candidates_consolidated"] = {
            "sobre_1_tecnico": [{}],
            "candidate_document_list": [],
        }
        return state["document_candidates_consolidated"]

    async def _ensure_checklist(mem, sid):
        state["submission_checklist"] = {"hitos": [{}] * 6}
        return fake_checklist

    async def _build_junta(mem, sid, **kwargs):
        state["junta_aclaraciones_questions"] = {"items": [{}, {}]}
        return fake_bundle

    with patch(
        "app.services.document_candidate_list_service.ensure_session_document_candidates",
        new=AsyncMock(side_effect=_ensure_candidates),
    ), patch(
        "app.checklist.submission_checklist_service.ensure_session_cronograma_and_checklist",
        new=AsyncMock(side_effect=_ensure_checklist),
    ), patch(
        "app.services.junta_aclaraciones_questions_service.build_and_persist_junta_aclaraciones_questions",
        new=AsyncMock(side_effect=_build_junta),
    ), patch(
        "app.services.session_bases_analysis_invalidation.commit_bases_analysis_snapshot",
        return_value={"pending_reanalysis": False, "committed_at": "2026-01-01T00:00:00Z"},
    ):
        state["mini_dictamen_anexos"] = {"schema_version": "1"}
        result = await rehydrate_analysis_artifacts(mem, "sess_x", commit_snapshot=True)

    assert result.success is True
    assert result.preserved_keys_intact is True
    assert result.snapshot_committed is True
    assert state["bases_analysis_snapshot"]["pending_reanalysis"] is False
    assert len(state["economic_user_inputs"]) == 2
    assert state.get("generation_state") == {"status": "blocked"}


@pytest.mark.asyncio
async def test_rehydrate_idempotent_second_call():
    state = _session_with_compliance()
    state.update(
        {
            "document_candidates_consolidated": {"sobre_1_tecnico": [{}] * 3},
            "submission_checklist": {"hitos": [{}] * 6},
            "junta_aclaraciones_questions": {"items": [{}] * 4},
            "mini_dictamen_anexos": {},
        }
    )

    async def _get_session(sid):
        return state

    async def _save_session(sid, patch):
        state.update(patch)
        return True

    mem = MagicMock()
    mem.get_session = AsyncMock(side_effect=_get_session)
    mem.save_session = AsyncMock(side_effect=_save_session)
    mem.get_documents = AsyncMock(return_value=[])

    fake_bundle = MagicMock()
    fake_bundle.items = [{}] * 4
    fake_cl = MagicMock()
    fake_cl.hitos = [MagicMock()] * 6

    with patch(
        "app.services.document_candidate_list_service.ensure_session_document_candidates",
        new=AsyncMock(return_value=state["document_candidates_consolidated"]),
    ), patch(
        "app.checklist.submission_checklist_service.ensure_session_cronograma_and_checklist",
        new=AsyncMock(return_value=fake_cl),
    ), patch(
        "app.services.junta_aclaraciones_questions_service.build_and_persist_junta_aclaraciones_questions",
        new=AsyncMock(return_value=fake_bundle),
    ), patch(
        "app.services.session_bases_analysis_invalidation.commit_bases_analysis_snapshot",
        return_value={"pending_reanalysis": False},
    ):
        r1 = await rehydrate_analysis_artifacts(mem, "sess_y")
        r2 = await rehydrate_analysis_artifacts(mem, "sess_y")

    assert r1.success is True
    assert r2.success is True
    assert len(state["economic_user_inputs"]) == 2


@pytest.mark.asyncio
async def test_rehydrate_after_pipeline_failure_sets_stop_reason():
    state = _session_with_compliance()

    async def _get_session(sid):
        return state

    async def _save_session(sid, patch):
        state.update(patch)
        return True

    mem = MagicMock()
    mem.get_session = AsyncMock(side_effect=_get_session)
    mem.save_session = AsyncMock(side_effect=_save_session)

    with patch(
        "app.services.analysis_artifacts_rehydrate_service.rehydrate_analysis_artifacts",
        new=AsyncMock(
            return_value=RehydrateAnalysisArtifactsResult(
                session_id="sess_fail",
                success=False,
                error="core_steps_incomplete",
                steps=[RehydrateStepResult(step="junta_aclaraciones_questions", ok=False)],
            )
        ),
    ):
        from app.services.analysis_artifacts_rehydrate_service import (
            REHYDRATE_STOP_REASON,
            rehydrate_after_analysis_pipeline,
        )

        result = await rehydrate_after_analysis_pipeline(mem, "sess_fail")

    assert result.success is False
    assert state["last_orchestrator_decision"]["stop_reason"] == REHYDRATE_STOP_REASON
