"""Tests HTTP health + rehydrate routes P2-04."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.analysis_artifacts_rehydrate_service import (
    RehydrateAnalysisArtifactsResult,
)


@pytest.mark.asyncio
async def test_get_session_health_route():
    from app.api.v1.routes.sessions import get_session_health

    state = {
        "compliance_master_list": {"administrativo": [{}]},
        "submission_checklist": {"hitos": [{}] * 6},
        "junta_aclaraciones_questions": {"items": [{}], "summary": {"total": 1}},
        "document_candidates_consolidated": {"sobre_1_tecnico": [{}]},
        "dictamen": {"zones": [{}]},
        "bases_analysis_snapshot": {"pending_reanalysis": False, "fingerprint": "a"},
    }
    mem = MagicMock()
    mem.get_session = AsyncMock(return_value=state)
    mem.disconnect = AsyncMock(return_value=None)

    with patch(
        "app.api.v1.routes.sessions.get_repository",
        new=AsyncMock(return_value=mem),
    ):
        resp = await get_session_health("vigilancia_issste")

    assert resp.success is True
    sh = resp.data["session_health"]
    assert sh["artifacts"]["hitos"] == 6
    assert "rehydrate_recommended" in sh


@pytest.mark.asyncio
async def test_post_rehydrate_route_sync():
    from app.api.v1.routes.sessions import post_rehydrate_analysis_artifacts

    mem = MagicMock()
    mem.get_session = AsyncMock(
        return_value={
            "compliance_master_list": {"administrativo": [{}]},
            "submission_checklist": {"hitos": [{}] * 6},
            "junta_aclaraciones_questions": {"items": [{}] * 5},
            "document_candidates_consolidated": {"sobre_1_tecnico": [{}] * 26},
            "dictamen": {"zones": [{}]},
            "bases_analysis_snapshot": {"pending_reanalysis": False},
        }
    )
    mem.disconnect = AsyncMock(return_value=None)

    fake = RehydrateAnalysisArtifactsResult(
        session_id="vigilancia_issste",
        success=True,
        counts={"hitos": 6, "junta_items": 5},
        snapshot_committed=True,
    )

    bg = MagicMock()

    with patch(
        "app.api.v1.routes.sessions.get_repository",
        new=AsyncMock(return_value=mem),
    ), patch(
        "app.services.analysis_artifacts_rehydrate_service.rehydrate_after_analysis_pipeline",
        new=AsyncMock(return_value=fake),
    ):
        resp = await post_rehydrate_analysis_artifacts(
            "vigilancia_issste",
            bg,
            None,
            sync=True,
        )

    assert resp.success is True
    assert resp.data["rehydrate"]["success"] is True
    assert resp.data.get("async") is False


@pytest.mark.asyncio
async def test_post_rehydrate_route_async_enqueues_job():
    from app.api.v1.routes.sessions import post_rehydrate_analysis_artifacts

    mem = MagicMock()
    mem.get_session = AsyncMock(return_value={"name": "Demo"})
    mem.disconnect = AsyncMock(return_value=None)
    bg = MagicMock()

    with patch(
        "app.api.v1.routes.sessions.get_repository",
        new=AsyncMock(return_value=mem),
    ), patch(
        "app.services.job_service.get_active_session_maintenance_job",
        return_value={},
    ), patch(
        "app.services.session_maintenance_job_service.create_rehydrate_job",
        return_value="job-rehydrate-1",
    ), patch(
        "app.services.session_maintenance_job_service.run_rehydrate_job_in_thread",
        new=AsyncMock(),
    ):
        resp = await post_rehydrate_analysis_artifacts(
            "vigilancia_issste",
            bg,
            None,
            sync=False,
        )

    assert resp.status_code == 202
    body = resp.body.decode() if hasattr(resp, "body") else str(resp)
    assert "job-rehydrate-1" in body
    bg.add_task.assert_called_once()
