"""Tests HRU: deducciones operativas sin referencias a convocante (ISSSTE/IMSS)."""

from __future__ import annotations

from app.agents.chatbot_rag import ChatbotRAGAgent
from app.services.operational_deduction_ux import (
    apply_operational_deduction_post_llm,
    build_fallback_deduction_bullet,
    detect_operational_personnel_penalty_intent,
    extract_deduction_bullet_from_fragments,
    load_operational_deduction_ux_messages,
    policy_version,
)


def test_policy_version_present():
    assert policy_version().startswith("operational-deduction-")


def test_detect_operational_intent_without_vigilancia_keyword():
    q = "¿Qué deducción aplica si un elemento falta a su turno y no hay cobertura?"
    assert detect_operational_personnel_penalty_intent(q) is True
    assert ChatbotRAGAgent._detect_operational_personnel_penalty_intent(q) is True


def test_detect_operational_intent_false_when_contractual_penalty():
    q = (
        "Detalla las penas convencionales aplicables por atraso o incumplimiento, "
        "el mecanismo de cobro sobre saldos pendientes y el límite financiero "
        "respecto a la garantía de cumplimiento."
    )
    assert detect_operational_personnel_penalty_intent(q, penalty_intent=True) is False
    assert ChatbotRAGAgent._detect_operational_personnel_penalty_intent(q) is False


def test_fallback_bullet_has_no_issste_imss():
    bullet = build_fallback_deduction_bullet().lower()
    assert "issste" not in bullet
    assert "imss" not in bullet
    assert "páginas 68" not in bullet


def test_extract_from_fragment_uses_excerpt_not_hardcoded_pages():
    doc = (
        "Las deducciones por turno no cubierto: por cada elemento que falte "
        "se descontará el 100% de la cuota diaria del servicio no prestado "
        "y una penalización del 2% sobre la facturación del periodo."
    )
    out = extract_deduction_bullet_from_fragments([doc])
    assert "68-70" not in out
    assert "issste" not in out.lower()
    assert "por cada elemento" in out.lower()


def test_post_llm_corrects_goods_mora_hallucination():
    hallucination = (
        "se aplicará una pena convencional del 2.5% por día natural de mora "
        "sobre el valor de los bienes pendientes de entregar, hasta su cumplimiento "
        "a entera satisfacción del Instituto."
    )
    out = apply_operational_deduction_post_llm(hallucination, context_docs=[])
    low = out.lower()
    assert "issste" not in low
    assert "imss" not in low
    assert "bienes pendientes" not in low
    assert "deducciones operativas" in low or "deducción" in low
    assert "turno no cubierto" in low or "según bases" in low


def test_ux_messages_insolvency_alert_universal():
    alert = str(load_operational_deduction_ux_messages().get("insolvency_budget_alert") or "").lower()
    assert "issste" not in alert
    assert "anexo 9" not in alert
