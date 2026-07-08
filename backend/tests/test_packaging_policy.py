"""Tests HRU de política de empaquetado parcial (F3.3)."""

from __future__ import annotations

import pytest

from app.services.packaging_policy import (
    expected_sobres,
    partial_manifest_label,
    policy_version,
    require_all_sobres,
)


def test_packaging_policy_version():
    assert policy_version()


def test_expected_sobres_universal():
    sobres = expected_sobres()
    assert "SobreComplementaria" in sobres
    assert "SobreTecnica" in sobres
    assert "SobreEconomica" in sobres


def test_partial_label_not_empty():
    assert partial_manifest_label()


def test_require_all_sobres_default_false():
    assert require_all_sobres() is False


def test_require_all_sobres_strict(monkeypatch):
    from app.config.settings import settings

    monkeypatch.setattr(settings, "PACKAGING_REQUIRE_ALL_SOBRES", True)
    from app.services import packaging_policy as pp

    pp.load_packaging_policy.cache_clear()
    assert pp.require_all_sobres() is True
