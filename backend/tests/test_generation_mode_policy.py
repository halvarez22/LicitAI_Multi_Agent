"""Tests HRU de política de modos de generación (F2)."""

from __future__ import annotations

import pytest

from app.services.generation_mode_policy import (
    active_jobs_for_mode,
    decoupled_generation_enabled,
    normalize_generation_mode,
    policy_version,
    resolve_generation_mode_from_input,
    skipped_jobs_for_mode,
    wipe_preserve_subdirs_for_mode,
)


def test_policy_version_present():
    assert policy_version()


def test_normalize_aliases():
    assert normalize_generation_mode("generation_technical") == "technical"
    assert normalize_generation_mode("generation_economic") == "economic"
    assert normalize_generation_mode("generation_full") == "full"


def test_technical_mode_skips_economic_jobs():
    skipped = skipped_jobs_for_mode("technical")
    assert "economic_writer" in skipped
    assert "technical" in active_jobs_for_mode("technical")
    assert "formats" in active_jobs_for_mode("technical")


def test_economic_mode_only_economic_writer():
    active = active_jobs_for_mode("economic")
    assert active == frozenset({"economic_writer"})
    assert "technical" in skipped_jobs_for_mode("economic")


def test_technical_wipe_preserves_economic_folder():
    preserve = wipe_preserve_subdirs_for_mode("technical")
    assert "2.propuesta_economica" in preserve


def test_resolve_generation_mode_precedence():
    resolved = resolve_generation_mode_from_input(
        {
            "generation_mode": "technical",
            "company_data": {"generation_mode": "economic"},
        }
    )
    assert resolved == "technical"


def test_resolve_from_session_state():
    resolved = resolve_generation_mode_from_input(
        {},
        {"generation_state": {"generation_mode": "economic"}},
    )
    assert resolved == "economic"


def test_decoupled_disabled_forces_full(monkeypatch):
    monkeypatch.setattr(
        "app.services.generation_mode_policy.decoupled_generation_enabled",
        lambda: False,
    )
    assert normalize_generation_mode("technical") == "full"
