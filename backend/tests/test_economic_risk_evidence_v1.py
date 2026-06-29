"""Tests HRU policy v1.3 y contrato evidence_v1."""
from __future__ import annotations

from app.services.economic_alert_classifier import (
    _load_policy,
    ux_reason_for_subtype,
    normalize_economic_alert,
    SUBTYPE_AMBIGUOUS_PRESUPUESTO,
)
from app.services.economic_risk_evidence_v1 import build_evidence_v1, MODE_INDEX_VERIFIED, MODE_INFERENCE_ONLY

PRESUPUESTO_LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"


def test_policy_v14_has_ux_reasons_and_promotion_gate():
    policy = _load_policy()
    assert policy.get("policy_version", "").startswith("economic-alert-v1.4")
    assert "ux_reason_by_subtype" in policy
    assert policy.get("evidence_schema_version") == "economic_risk_evidence_v1"
    assert policy.get("promotion_requires_index_verified") is True


def test_ux_reason_ambiguous_from_policy():
    reason = ux_reason_for_subtype(SUBTYPE_AMBIGUOUS_PRESUPUESTO)
    assert "piso de tu oferta" in reason.lower() or "presupuesto autorizado" in reason.lower()


def test_normalize_uses_ambiguous_subtype_for_presupuesto_literal():
    norm = normalize_economic_alert(PRESUPUESTO_LITERAL)
    assert norm["alert_subtype"] == SUBTYPE_AMBIGUOUS_PRESUPUESTO
    assert "presupuesto" in norm["risk_reason_ux"].lower()


def test_evidence_v1_index_verified_mode():
    ev = build_evidence_v1(
        {"page": 30, "snippet": "propuesta no menor a $1,000,000", "match_confidence": "alta", "provenance": "index_scan"},
        literal=PRESUPUESTO_LITERAL,
    )
    assert ev["evidence_mode"] == MODE_INDEX_VERIFIED
    assert ev["page"] == 30


def test_evidence_v1_inference_only_without_page():
    ev = build_evidence_v1({"match_confidence": "none"}, literal=PRESUPUESTO_LITERAL)
    assert ev["evidence_mode"] == MODE_INFERENCE_ONLY
