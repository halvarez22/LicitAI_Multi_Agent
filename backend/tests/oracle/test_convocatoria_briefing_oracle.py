"""Oracle F11: briefing de convocatoria y apertura HRU."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.chat_opening_orchestrator import resolve_chat_opening
from app.services.convocatoria_briefing_service import build_convocatoria_briefing_canonical_v1
from app.services.convocatoria_briefing_ux import render_opening_message

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "convocatoria_briefing" / "oracle_cases.json"


@pytest.fixture(scope="module")
def oracle_cases():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", json.loads(_FIXTURE.read_text(encoding="utf-8")), ids=lambda c: c["case_id"])
def test_convocatoria_briefing_oracle(case, monkeypatch):
    monkeypatch.setattr(
        "app.services.convocatoria_briefing_service.convocatoria_briefing_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.chat_opening_orchestrator.chat_opening_orchestrator_enabled",
        lambda: True,
    )
    state = dict(case["session_state"])
    briefing = build_convocatoria_briefing_canonical_v1(state)
    assert briefing.get("schema_version", "").startswith("convocatoria-briefing-v1")
    assert len(briefing.get("blocks") or []) >= int(case.get("expect_blocks_min") or 3)
    assert briefing.get("recommended_first_track") == case["expect_first_track"]
    if case.get("expect_confidence"):
        assert (briefing.get("quality_signals") or {}).get("confidence") == case["expect_confidence"]

    opening = render_opening_message(session_state=state, briefing=briefing)
    blob = opening.lower()
    for token in case.get("expect_opening_contains") or []:
        assert token.lower() in blob, f"{case['case_id']}: missing {token}"
    for token in case.get("forbid_opening_contains") or []:
        assert token.lower() not in blob, f"{case['case_id']}: forbidden {token}"

    result = resolve_chat_opening(
        session_state={**state, "convocatoria_briefing_v1": briefing},
        pending_questions=[],
        current_idx=0,
        user_query="hola",
        company_id="company-test",
    )
    assert result is not None
    assert result.briefing_v1.get("recommended_first_track") == case["expect_first_track"]
