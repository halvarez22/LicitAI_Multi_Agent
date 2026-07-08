"""Tests política HRU de misión del expediente."""

from __future__ import annotations

from app.services.expediente_mission_policy import (
    humanize_technical_slot_label,
    is_document_shell_technical_label,
    policy_version,
    session_signals_service_pricing,
)


def test_policy_version():
    assert policy_version().startswith("expediente-mission-")


def test_document_shell_detection():
    assert is_document_shell_technical_label("Propuesta Técnica describiendo especificaciones")
    assert not is_document_shell_technical_label("Personal mínimo por turno")


def test_humanize_methodology():
    label = humanize_technical_slot_label(
        "Propuesta Técnica describiendo especificaciones",
        "free_text_annex",
    )
    assert "presentar_fisico" not in label.lower()
    assert len(label) < 80


def test_vigilancia_strong_keyword_without_analysis_flag():
    assert session_signals_service_pricing({"name": "VIGILANCIA ISSSTE"}) is True
