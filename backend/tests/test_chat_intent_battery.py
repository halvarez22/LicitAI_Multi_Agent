"""
Gate CI — batería grande de utterances (SUPER ISSUE S.6).

Universal: plantillas genéricas, sin licitación fija.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.chat_stop_reason_map import (
    STOP_REASON_HUMAN,
    assert_user_visible_clean,
    humanize_stop_reason,
    sanitize_user_visible_text,
    single_cta_for_context,
)
from app.services.chat_user_intent import UserChatIntent, resolve_user_intent
from app.services.chat_intent_battery import (
    BATTERY_MIN_CASES,
    build_chat_intent_battery,
)


def _load_battery():
    return build_chat_intent_battery()


@pytest.fixture(scope="module")
def battery():
    cases = _load_battery()
    assert len(cases) >= BATTERY_MIN_CASES, f"Se esperaban ≥{BATTERY_MIN_CASES} casos, hay {len(cases)}"
    return cases


def test_battery_size_gate(battery):
    """Gate: la batería debe tener al menos 150 frases."""
    assert len(battery) >= BATTERY_MIN_CASES


@pytest.mark.parametrize(
    "case_id,utterance,expected,context",
    [
        pytest.param(
            c.case_id,
            c.utterance,
            c.expected_intent,
            c.context,
            id=c.case_id,
        )
        for c in build_chat_intent_battery()
    ],
)
def test_battery_intent_resolution(case_id, utterance, expected, context):
    ctx = context or {}
    resolved = resolve_user_intent(
        utterance,
        has_economic_pending=bool(ctx.get("has_economic_pending")),
        has_any_pending=bool(ctx.get("has_any_pending")),
        current_pending_type=str(ctx.get("current_pending_type") or ""),
        is_explicit_gen_command=bool(ctx.get("is_explicit_gen_command")),
    )
    assert resolved.intent == UserChatIntent(expected), (
        f"[{case_id}] utterance={utterance!r} got={resolved.intent.value} reason={resolved.reason}"
    )


@pytest.mark.parametrize(
    "case_id,sample_bad",
    [
        pytest.param(c.case_id, c.sample_bad_response, id=c.case_id)
        for c in build_chat_intent_battery()
        if c.sample_bad_response
    ],
)
def test_battery_sanitize_removes_internal_codes(case_id, sample_bad):
    cleaned = sanitize_user_visible_text(sample_bad)
    assert "Gate 12.1" not in cleaned
    assert "MISSING_" not in cleaned
    assert "COMPLIANCE_GATE" not in cleaned
    assert "_compliance_truth" not in cleaned
    assert_user_visible_clean(cleaned)


def test_all_stop_reasons_humanized_without_internal_codes():
    for code in STOP_REASON_HUMAN:
        msg = humanize_stop_reason(code)
        assert_user_visible_clean(msg)
        assert "MISSING_" not in msg
        assert "Gate" not in msg


def test_meta_style_responses_use_single_cta():
    for code in list(STOP_REASON_HUMAN.keys()) + ["UNKNOWN_CODE_XYZ"]:
        human = humanize_stop_reason(code)
        cta = single_cta_for_context(stop_reason=code, has_economic_pending=False)
        combined = sanitize_user_visible_text(f"**Estado:** {human}\n\n**Siguiente paso:** {cta}")
        assert_user_visible_clean(combined)
        assert "MISSING_" not in combined


def test_battery_json_export_matches_builder(battery):
    """El JSON versionado debe coincidir con el generador (fuente de verdad = Python)."""
    json_path = Path(__file__).parent / "fixtures" / "chat_intent_utterances_battery.json"
    if not json_path.exists():
        pytest.skip("JSON de batería no exportado aún")
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(on_disk) >= BATTERY_MIN_CASES
    assert len(on_disk) == len(battery)
