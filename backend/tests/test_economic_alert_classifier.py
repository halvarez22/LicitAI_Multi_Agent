"""Tests HRU: desambiguación por evidencia, moneda de sesión, chat conversacional."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.services.economic_alert_classifier import (
    SUBTYPE_AMBIGUOUS_PRESUPUESTO,
    SUBTYPE_OFFER_FLOOR,
    classify_economic_alert_text,
    disambiguate_subtype_with_evidence,
    normalize_and_dedupe_economic_alerts,
    resolve_session_currency,
)
from app.services.forensic_risk_chat_service import (
    build_forensic_risk_chat_reply,
    try_answer_forensic_risk_question,
)

PRESUPUESTO_LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"
LICITANTE_SNIPPET = (
    "El licitante deberá presentar propuesta económica no menor a $1,000,000.00 MXN."
)


def test_presupuesto_literal_is_ambiguous_without_snippet():
    assert classify_economic_alert_text(PRESUPUESTO_LITERAL) == SUBTYPE_AMBIGUOUS_PRESUPUESTO


def test_presupuesto_disambiguates_to_offer_floor_with_licitante_snippet():
    base = classify_economic_alert_text(PRESUPUESTO_LITERAL)
    refined = disambiguate_subtype_with_evidence(base, PRESUPUESTO_LITERAL, LICITANTE_SNIPPET)
    assert refined == SUBTYPE_OFFER_FLOOR


def test_currency_from_session_not_hardcoded():
    state = {
        "tasks_completed": {
            "economic": {"data": {"currency": "USD"}},
        }
    }
    assert resolve_session_currency(state) == "USD"
    assert resolve_session_currency({}) == ""


def test_conversational_reply_ambiguous_without_evidence():
    ctx = {"literal": PRESUPUESTO_LITERAL}
    reply = build_forensic_risk_chat_reply(ctx, evidence={})
    assert "piso de tu oferta o presupuesto autorizado" in reply.lower()
    assert "El agente económico detectó" not in reply
    assert "MXN" not in reply or "1,000,000" in reply


def test_conversational_reply_offer_floor_when_snippet_confirms():
    ctx = {"literal": PRESUPUESTO_LITERAL}
    evidence = {"page": 12, "snippet": LICITANTE_SNIPPET, "match_confidence": "alta"}
    reply = build_forensic_risk_chat_reply(
        ctx,
        evidence=evidence,
        session_state={"tasks_completed": {"economic": {"data": {"currency": "MXN"}}}},
    )
    assert "piso de oferta" in reply.lower()
    assert "página 12" in reply.lower()
    assert "1,000,000" in reply


def test_conversational_reply_no_page_without_verified_evidence():
    ctx = {"literal": PRESUPUESTO_LITERAL}
    reply = build_forensic_risk_chat_reply(
        ctx,
        evidence={"page": 1, "snippet": "portada del pliego", "match_confidence": "baja"},
    )
    assert "página 1" not in reply.lower()


def test_conversational_reply_without_page_suggests_amount_not_paraphrase():
    ctx = {"literal": PRESUPUESTO_LITERAL}
    reply = build_forensic_risk_chat_reply(ctx, evidence={})
    assert "$1,000,000" in reply
    assert "análisis económico" in reply.lower() or "monto" in reply.lower()
    assert "busca el texto «El presupuesto debe ser" not in reply


def test_bases_coherence_still_excluded():
    alerts = [PRESUPUESTO_LITERAL, "[Bases] criterio_importe_minimo: $500,000 — revisar coherencia."]
    forensic, excluded = normalize_and_dedupe_economic_alerts(alerts)
    assert len(forensic) == 0
    assert len(excluded) == 2


def test_llm_refine_fallback_to_template_when_no_snippet():
    async def _run():
        ctx = {"force_grounded": True, "literal": PRESUPUESTO_LITERAL}
        with patch(
            "app.services.forensic_risk_evidence_service.resolve_forensic_risk_evidence",
            new_callable=AsyncMock,
            return_value={},
        ):
            out = await try_answer_forensic_risk_question("Explícame", ctx, session_id="s1")
        assert out is not None
        reply = out.get("respuesta") if isinstance(out, dict) else str(out)
        assert "presupuesto" in reply.lower()

    asyncio.run(_run())
