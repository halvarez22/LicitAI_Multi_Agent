"""Tests HRU política piloto on-premise (F10)."""

from __future__ import annotations

from app.services.pilot_onprem_policy import (
    evaluate_pilot_runtime,
    pilot_profile_flags,
    policy_version,
    signoff_criteria,
)


def test_pilot_policy_version():
    assert policy_version()


def test_pilot_profile_has_f0_f10_flags():
    flags = pilot_profile_flags()
    assert flags.get("ADMIN_ECONOMIC_DEFERRAL") is True
    assert flags.get("DECOUPLED_GENERATION_ENABLED") is True
    assert flags.get("DUAL_STREAM_ENABLED") is True
    assert flags.get("ECONOMIC_CHAT_CALC_ON_CAPTURE") is True
    assert flags.get("TECHNICAL_CHAT_FIRST") is True
    assert flags.get("COPILOT_UNIFIED_STATUS") is True
    assert flags.get("PACKAGING_REQUIRE_ALL_SOBRES") is False
    assert flags.get("CONTEXTUAL_DOWNLOAD_ENABLED") is True


def test_signoff_criteria_count():
    criteria = signoff_criteria()
    assert len(criteria) >= 10
    ids = {c.get("id") for c in criteria}
    assert "chat_only_quoting" in ids
    assert "parallel_dual_stream" in ids
    assert "dual_copilot_status" in ids
    assert "no_internal_codes_in_ux" in ids


def test_evaluate_pilot_runtime_ok_by_default():
    report = evaluate_pilot_runtime()
    assert report.get("policy_version")
    assert report.get("errors") == []
    assert isinstance(report.get("profile_matches"), dict)
