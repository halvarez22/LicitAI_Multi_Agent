"""Tests de redacción universal para tickets y junta."""
from app.services.clarification_ticket_copy import (
    build_junta_question_from_clarification_ticket,
    build_ticket_summary_for_hitl,
    humanize_clarification_reason,
    is_internal_ticket_draft,
)
from app.services.junta_aclaraciones_questions_service import (
    build_junta_aclaraciones_questions,
    bundle_needs_regeneration,
)


def test_humanize_reason_required_annex():
    assert "expediente" in humanize_clarification_reason("required_annex_not_published")


def test_internal_ticket_draft_detected():
    assert is_internal_ticket_draft(
        "Necesito aclarar con la convocante el documento **Forma AE-01**. "
        "Motivo detectado: required_annex_not_published. "
        "¿Deseas prepararlo como punto para la junta de aclaraciones?"
    )


def test_hitl_summary_not_asking_deseas():
    text = build_ticket_summary_for_hitl("Forma AE-01", "required_annex_not_published")
    assert "¿Deseas prepararlo" not in text
    assert "Forma AE-01" in text


def test_junta_question_from_legacy_ticket():
    q = build_junta_question_from_clarification_ticket(
        {
            "display_name": "Forma AE-01",
            "reason": "required_annex_not_published",
            "question": (
                "Necesito aclarar con la convocante el documento **Forma AE-01**. "
                "Motivo detectado: required_annex_not_published. "
                "¿Deseas prepararlo como punto para la junta de aclaraciones?"
            ),
        }
    )
    assert "¿Deseas prepararlo" not in q
    assert "Motivo detectado" not in q
    assert "Forma AE-01" in q
    assert q.strip().endswith("?")


def test_junta_bundle_regenerates_on_internal_leak():
    payload = {
        "schema_version": "1.1.1",
        "items": [
            {
                "pregunta": (
                    "Con respecto al apartado Forma AE-01, donde la convocante establece que "
                    "Necesito aclarar... ¿Deseas prepararlo como punto para la junta?"
                ),
                "source": "mini_dictamen",
            }
        ],
    }
    assert bundle_needs_regeneration(payload) is True


def test_junta_bundle_from_mini_ticket_no_internal_leak():
    state = {
        "clarification_tickets": [
            {
                "ticket_id": "clar_forma_ae_01",
                "display_name": "Forma AE-01",
                "status": "open",
                "reason": "required_annex_not_published",
                "question": (
                    "Necesito aclarar con la convocante el documento **Forma AE-01**. "
                    "Motivo detectado: required_annex_not_published. "
                    "¿Deseas prepararlo como punto para la junta de aclaraciones?"
                ),
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("sess_test", state)
    assert bundle.items
    pregunta = bundle.items[0].pregunta
    assert "¿Deseas prepararlo" not in pregunta
    assert "Motivo detectado" not in pregunta
    assert "convocante" in pregunta.lower()
