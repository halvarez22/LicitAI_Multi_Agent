"""Tests HRU de política de alcances de descarga contextual (F5.1)."""

from __future__ import annotations

import pytest

from app.services.delivery_scope_policy import (
    allowed_delivery_extensions,
    contextual_download_enabled,
    empty_reason_message,
    generation_jobs_hint_for_scope,
    include_directories_for_scope,
    max_artifacts_list,
    normalize_delivery_scope,
    policy_version,
    prefer_compranet_validated_for_scope,
    scope_cta_download,
    scope_for_generation_mode,
    scope_label,
    ux_messages_version,
    valid_delivery_scopes,
)


def test_policy_version_present():
    assert policy_version() == "1.0.0"


def test_ux_messages_version_present():
    assert ux_messages_version()


def test_valid_scopes():
    scopes = valid_delivery_scopes()
    assert scopes == frozenset({"technical", "economic", "full"})


def test_normalize_aliases():
    assert normalize_delivery_scope("tecnica") == "technical"
    assert normalize_delivery_scope("eco") == "economic"
    assert normalize_delivery_scope("expediente") == "full"
    assert normalize_delivery_scope("") == "full"


def test_technical_scope_includes_tech_and_admin_dirs():
    dirs = include_directories_for_scope("technical")
    assert "1.propuesta tecnica" in dirs
    assert "3.documentos administrativos" in dirs


def test_economic_scope_directories():
    dirs = include_directories_for_scope("economic")
    assert "2.propuesta_economica" in dirs


def test_full_scope_prefers_compranet_validated():
    assert prefer_compranet_validated_for_scope("full") is True
    assert prefer_compranet_validated_for_scope("technical") is False


def test_generation_jobs_hint():
    assert "technical" in generation_jobs_hint_for_scope("technical")
    assert "formats" in generation_jobs_hint_for_scope("technical")
    assert generation_jobs_hint_for_scope("economic") == ["economic_writer"]


def test_scope_labels_human_not_disk_paths():
    label = scope_label("technical")
    assert "propuesta" in label.lower()
    assert "1." not in label


def test_cta_download_present():
    assert "técnica" in scope_cta_download("technical").lower() or "tecnica" in scope_cta_download(
        "technical"
    ).lower()


def test_allowed_extensions():
    exts = allowed_delivery_extensions()
    assert ".docx" in exts
    assert ".pdf" in exts


def test_max_artifacts_list_sane():
    assert 1 <= max_artifacts_list() <= 500


def test_empty_reason_message_known_key():
    msg = empty_reason_message("prices_required")
    assert "precio" in msg.lower() or "cotización" in msg.lower()


def test_empty_reason_message_unknown_key_fallback():
    msg = empty_reason_message("unknown_reason_xyz")
    assert len(msg) > 10


def test_scope_for_generation_mode_mapping():
    assert scope_for_generation_mode("technical") == "technical"
    assert scope_for_generation_mode("economic") == "economic"
    assert scope_for_generation_mode("full") == "full"


def test_contextual_download_disabled_defaults_full_scope(monkeypatch):
    monkeypatch.setattr(
        "app.services.delivery_scope_policy.contextual_download_enabled",
        lambda: False,
    )
    assert normalize_delivery_scope("technical") == "full"
