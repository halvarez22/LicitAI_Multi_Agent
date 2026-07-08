"""Tests política universal fill-quality en cola chat."""

from __future__ import annotations

from app.services.chat_fill_quality_queue_policy import (
    fill_quality_needs_chat_capture,
    should_exclude_fill_quality_from_chat,
    should_skip_fill_quality_rag_reminder,
)
from app.services.hitl_queue_service import sanitize_chat_pending_questions


def _template_issues() -> list:
    return [
        {
            "error_type": "cross_tender_reference",
            "detected_value": "PORCENTAJE",
            "document_id": "Formato T-b 1.docx",
        }
    ]


def test_template_issues_no_chat_capture():
    assert fill_quality_needs_chat_capture(_template_issues(), {"name": "Obra X"}) is False


def test_rfc_missing_needs_chat():
    issues = [
        {
            "error_type": "required_field_missing",
            "field_key": "rfc",
            "document_id": "profile",
        }
    ]
    assert fill_quality_needs_chat_capture(issues, {}) is True


def test_exclude_fill_quality_from_chat_universal():
    state = {
        "last_document_fill_quality_waiting_hints": {
            "blocking_count": 1,
            "issues": _template_issues(),
        }
    }
    q = {
        "type": "quality_validation_blocking",
        "field": "quality.fill.review",
        "label": "Datos para llenar documentos",
    }
    assert should_exclude_fill_quality_from_chat(q, state) is True
    assert should_skip_fill_quality_rag_reminder(q, state) is True


def test_sanitize_strips_fill_quality_servicios():
    state = {
        "name": "Limpieza demo",
        "triage_context": {"tender_category": "SERVICIOS"},
        "last_document_fill_quality_waiting_hints": {
            "blocking_count": 2,
            "issues": _template_issues(),
        },
    }
    pending = [
        {
            "field": "quality.fill.review",
            "type": "quality_validation_blocking",
            "label": "Datos para llenar documentos",
        }
    ]
    out = sanitize_chat_pending_questions(pending, state)
    assert out == []


def test_deferred_economic_warnings_no_chat_capture():
    issues = [
        {
            "error_type": "required_field_missing",
            "field_key": "tarifa_mensual",
            "expected_rule": "deferred_to_economic_stage",
            "severity": "warn",
            "document_id": "calculo_costos.xlsx",
        }
    ]
    assert fill_quality_needs_chat_capture(issues, {"triage_context": {"tender_category": "SERVICIOS"}}) is False
