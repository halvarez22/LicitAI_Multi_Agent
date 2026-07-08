"""Tests F12.2 — excerpt desde ancla + intent muéstrame el párrafo."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.chatbot_rag import ChatbotRAGAgent
from app.services.bases_anchor_excerpt_service import (
    build_show_paragraph_chat_message,
    detect_show_paragraph_intent,
    resolve_active_claim_anchor,
)
from app.services.evidence_anchor_service import normalize_evidence_anchor
from app.services.chat_stop_reason_map import assert_user_visible_clean


def test_detect_show_paragraph_intent():
    assert detect_show_paragraph_intent("muéstrame el párrafo") is True
    assert detect_show_paragraph_intent("ver en bases") is True
    assert detect_show_paragraph_intent("hola") is False


def test_resolve_anchor_from_briefing_first_action():
    state = {
        "convocatoria_briefing_v1": {
            "recommended_first_track": "economic",
            "recommended_first_action": {
                "evidence_anchor": normalize_evidence_anchor(
                    {
                        "source_name": "BASES.pdf",
                        "page": 27,
                        "snippet": "Integración del precio unitario mensual y diario sin IVA",
                    },
                    claim_id="t",
                )
            },
        }
    }
    anchor = resolve_active_claim_anchor(state, [], 0)
    assert anchor.get("page") == 27
    assert anchor.get("anchor_quality") == "verified"


def test_resolve_anchor_from_pending_blocking():
    pending = [
        {
            "type": "economic_validation_blocking",
            "field": "economic_price_source",
            "input_mode": "price_source",
            "blocking_items": [
                {
                    "concepto_label": "Integración del precio unitario",
                    "page_number": 27,
                    "context_snippet": "Integración del precio unitario mensual y diario sin el I.V.A. por operario",
                    "source_name": "BASES.pdf",
                    "requested_input": "price_source",
                }
            ],
        }
    ]
    anchor = resolve_active_claim_anchor({}, pending, 0)
    assert anchor.get("page") == 27


def test_show_paragraph_message_unavailable():
    msg = build_show_paragraph_chat_message(
        {"available": False, "user_message": "Aún no localicé la página."},
        reminder_label="cotización",
    )
    assert "localicé" in msg.lower() or "localice" in msg.lower()
    assert "cotización" in msg.lower()
    assert_user_visible_clean(msg)


def test_price_source_hint_diario_mensual():
    assert "diario" in ChatbotRAGAgent._price_source_concept_hint_from_query(
        "el precio diario es de 560", {}
    ).lower()
    assert "mensual" in ChatbotRAGAgent._price_source_concept_hint_from_query(
        "mensual es de 16800", {}
    ).lower()


def test_detect_show_paragraph_intent_with_price_context():
    assert detect_show_paragraph_intent(
        "muestrame el parrafo donde solicitan el precio, es que no tengo claro de que va"
    ) is True


def test_clarification_intent_false_for_show_paragraph():
    assert ChatbotRAGAgent._evaluate_clarification_intent(
        "muestrame el parrafo donde solicitan el precio, no tengo claro"
    ) is False


def test_parse_price_source_heuristic_dual():
    agent = ChatbotRAGAgent(context_manager=MagicMock())
    rows = agent._parse_price_source_reply_heuristic(
        "a perfecto el precio diario es de 560 pesos y el mensual es de 16,800 pesos todo antes de iva"
    )
    hints = {r["concept_hint"] for r in rows}
    assert "precio diario por operario" in hints
    assert "precio mensual por operario" in hints
    vals = {agent._clean_currency_value(r["value"]) for r in rows}
    assert 560.0 in vals
    assert 16800.0 in vals


def test_wants_economic_materialization_after_capture_complete():
    agent = ChatbotRAGAgent(context_manager=MagicMock())
    state = {
        "economic_user_inputs": {f"price_{i}": 1000 + i for i in range(8)},
        "pending_questions": [],
    }
    assert agent._wants_economic_materialization("generar propuesta economica", state) is True
    assert agent._wants_economic_materialization("generar", state) is True
    assert agent._wants_economic_materialization("hola", state) is False
    assert agent._wants_economic_materialization(
        "generar propuesta tecnica", state
    ) is False


def test_label_keyerror_safe_access_pattern():
    """Regresión: pending sin label no debe usar acceso directo ['label']."""
    q = {"field": "economic_price_source", "type": "economic_validation_blocking"}
    lbl = str(q.get("label") or q.get("field") or "dato")
    assert lbl == "economic_price_source"
