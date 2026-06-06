"""Tests P2-04: session health service."""
from __future__ import annotations

from app.services.session_health_service import assess_session_health


def _rich_state(**overrides):
    base = {
        "compliance_master_list": {
            "administrativo": [{}] * 90,
            "tecnico": [{}] * 5,
            "formatos": [{}] * 26,
        },
        "submission_checklist": {"hitos": [{}] * 6},
        "junta_aclaraciones_questions": {
            "summary": {"total": 5},
            "items": [{}] * 5,
        },
        "document_candidates_consolidated": {"sobre_1_tecnico": [{}] * 26},
        "dictamen": {"zones": [{}]},
        "bases_analysis_snapshot": {
            "fingerprint": "x",
            "pending_reanalysis": False,
        },
    }
    base.update(overrides)
    return base


def test_health_ok_vigilancia_baseline():
    state = _rich_state()
    h = assess_session_health("vigilancia_issste", state)
    assert h["healthy"] is True
    assert h["rehydrate_recommended"] is False
    assert h["artifacts"]["hitos"] == 6
    assert h["artifacts"]["junta"] == 5


def test_health_recommends_rehydrate_pending_reanalysis():
    state = _rich_state(
        bases_analysis_snapshot={"pending_reanalysis": True},
    )
    h = assess_session_health("vigilancia_issste", state)
    assert h["rehydrate_recommended"] is True
    assert "bases_pending_reanalysis" in h["stale"]


def test_health_recommends_when_junta_missing():
    state = _rich_state(junta_aclaraciones_questions={"items": []})
    h = assess_session_health("vigilancia_issste", state)
    assert h["rehydrate_recommended"] is True
    assert any("junta" in s for s in h["stale"])
