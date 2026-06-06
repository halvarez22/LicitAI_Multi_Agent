"""Tests helpers del smoke P2-01 (sin Postgres)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.smoke_session_stability import (
    CHECKLIST_TIME_LIMIT_S,
    checklist_at_risk,
    count_hitos,
    count_junta_items,
    count_sobre_tecnico,
    evaluate_artifact_blockers,
    run_checklist_smoke,
)


def test_count_hitos_and_junta():
    state = {
        "submission_checklist": {"hitos": [{}] * 6},
        "junta_aclaraciones_questions": {
            "summary": {"total": 4},
            "items": [{}, {}, {}, {}],
        },
        "document_candidates_consolidated": {"sobre_1_tecnico": [{}] * 3},
        "dictamen": {"zones": []},
        "compliance_master_list": {"administrativo": [{}]},
    }
    assert count_hitos(state) == 6
    assert count_junta_items(state) == 4
    assert count_sobre_tecnico(state) == 3
    assert evaluate_artifact_blockers(state, min_hitos=6) == []


def test_evaluate_blockers_detects_gaps():
    state = {
        "compliance_master_list": {"administrativo": [{}]},
        "submission_checklist": {"hitos": [{}]},
        "junta_aclaraciones_questions": {"items": []},
    }
    blockers = evaluate_artifact_blockers(state, min_hitos=6)
    assert any("hitos_below_min" in b for b in blockers)
    assert any("junta_below_min" in b for b in blockers)
    assert "dictamen_missing" in blockers


def test_checklist_at_risk_pattern():
    state = {
        "submission_checklist": {"hitos": [{}] * 6},
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {"data": {"cronograma": None}}}
        ],
    }
    assert checklist_at_risk(state) is True


@pytest.mark.asyncio
async def test_run_checklist_smoke_recursion_fatal():
    mem = MagicMock()
    with patch(
        "app.checklist.submission_checklist_service.ensure_session_cronograma_and_checklist",
        new=AsyncMock(side_effect=RecursionError),
    ):
        ok, err, elapsed = await run_checklist_smoke(mem, "sess")

    assert ok is False
    assert err == "recursion"
    assert elapsed >= 0


@pytest.mark.asyncio
async def test_run_checklist_smoke_timeout_fatal():
    mem = MagicMock()

    async def _slow(*a, **k):
        import asyncio

        await asyncio.sleep(0.05)

    with patch(
        "app.checklist.submission_checklist_service.ensure_session_cronograma_and_checklist",
        new=_slow,
    ):
        ok, err, _ = await run_checklist_smoke(mem, "sess", time_limit_s=0.001)

    assert ok is False
    assert err == "timeout"
