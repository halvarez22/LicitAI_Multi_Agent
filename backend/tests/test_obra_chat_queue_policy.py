"""Tests política de cola chat obra — experiencia documental vs escalar perfil."""

from __future__ import annotations

from app.services.hitl_queue_service import sanitize_chat_pending_questions
from app.services.obra_chat_queue_policy import (
    enrich_inventory_payload_for_ui,
    filter_obra_fill_quality_issues,
    is_obra_session,
    normalize_obra_fill_quality_issue,
    obra_fill_quality_needs_chat_capture,
    obra_requires_documentary_experience,
    should_skip_datagap_field_for_session,
)
from app.services.document_fill_ux_messages import build_fill_blocking_question


def _barda_state() -> dict:
    return {
        "name": "BARDA PRIMARIA LOPEZ RAYON",
        "triage_context": {"tender_category": "OBRA", "law": "LOPSRM"},
        "compliance_master_list": {
            "formatos": [
                {"nombre": "Anexo T-2 contratos vigentes de obra"},
                {"nombre": "Documentación que compruebe su experiencia y capacidad técnica"},
            ],
        },
    }


def test_is_obra_session():
    assert is_obra_session(_barda_state()) is True
    assert is_obra_session({"triage_context": {"tender_category": "SERVICIOS"}}) is False


def test_obra_documentary_experience_detected():
    assert obra_requires_documentary_experience(_barda_state()) is True


def test_skip_anos_experiencia_for_obra():
    assert should_skip_datagap_field_for_session("anos_experiencia", _barda_state()) is True
    assert should_skip_datagap_field_for_session("rfc", _barda_state()) is False
    assert should_skip_datagap_field_for_session("anos_experiencia", {"triage_context": {"tender_category": "SERVICIOS"}}) is False


def test_sanitize_removes_experience_question_from_chat():
    pending = [
        {
            "question_id": "INTAKE-A-001",
            "field": "anos_experiencia",
            "type": "profile_field",
            "question": "¿Cuántos **años de experiencia** tiene la empresa?",
        },
        {
            "question_id": "ECO-001",
            "field": "line_item_1",
            "type": "economic_price",
            "question": "Precio unitario concepto 1",
        },
    ]
    out = sanitize_chat_pending_questions(pending, _barda_state())
    fields = {q.get("field") for q in out}
    assert "anos_experiencia" not in fields
    assert "line_item_1" in fields


def test_enrich_inventory_adds_nombre_alias():
    payload = {
        "items": [
            {
                "canonical_id": "anexo_t2",
                "display_name": "Anexo T-2 Contratos vigentes",
                "category": "technical",
                "status": "pending",
            }
        ]
    }
    out = enrich_inventory_payload_for_ui(payload)
    item = out["items"][0]
    assert item["nombre"] == "Anexo T-2 Contratos vigentes"
    assert item["nombre_canonico"] == "Anexo T-2 Contratos vigentes"


def test_normalize_obra_cross_tender_pliego_markers():
    issue = {
        "error_type": "cross_tender_reference",
        "detected_value": "PORCENTAJE",
        "document_id": "Formato T-b 1.docx",
    }
    norm = normalize_obra_fill_quality_issue(issue)
    assert norm["error_type"] == "placeholder_detected"


def test_obra_template_issues_do_not_need_chat_capture():
    state = _barda_state()
    issues = [
        {
            "error_type": "cross_tender_reference",
            "detected_value": "BASES",
            "document_id": "Anexo T-6.docx",
            "field_key": "content",
        },
        {
            "error_type": "placeholder_detected",
            "detected_value": "GANTT",
            "document_id": "Anexo E-4.docx",
            "field_key": "content",
        },
    ]
    filtered = filter_obra_fill_quality_issues(issues, state)
    assert obra_fill_quality_needs_chat_capture(filtered, state) is False


def test_sanitize_removes_obra_fill_quality_template_pending():
    state = _barda_state()
    state["last_document_fill_quality_waiting_hints"] = {
        "blocking_count": 2,
        "issues": [
            {
                "error_type": "cross_tender_reference",
                "detected_value": "GANTT",
                "document_id": "Anexo E-4.docx",
            }
        ],
    }
    pending = [
        {
            "field": "quality.fill.review",
            "label": "Datos para llenar documentos",
            "type": "quality_validation_blocking",
            "question": "mensaje viejo intimidante",
        }
    ]
    out = sanitize_chat_pending_questions(pending, state)
    assert out == []


def test_obra_fill_blocking_question_is_gate5_not_scary():
    state = _barda_state()
    issues = [
        {
            "error_type": "cross_tender_reference",
            "detected_value": "PORCENTAJE",
            "document_id": "Formato T-b 1.docx",
            "field_key": "content",
        }
    ]
    msg = build_fill_blocking_question("formats", issues, session_state=state)
    assert "otra licitación" not in msg.lower()
    assert "Pausé la generación" not in msg
    assert "Siguiente paso" in msg
    assert "Generar" in msg
