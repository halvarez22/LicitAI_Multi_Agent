"""Tests para evaluación HITL de riesgos forenses."""
from __future__ import annotations

from app.services.forensic_risk_service import (
    apply_risk_decision_updates,
    attach_forensic_risks_to_dictamen,
    build_forensic_risks_v1,
    can_continue_with_risks,
    enrich_risk_hallazgo,
    merge_risk_decisions_into_items,
)
from app.services.economic_alert_classifier import SUBTYPE_AMBIGUOUS_PRESUPUESTO


def test_enrich_risk_knockout_metadata():
    h = enrich_risk_hallazgo(
        {
            "tipo": "🚫 DESECHAMIENTO",
            "texto": "No presentar documentación falsa",
            "isRisk": True,
            "category": "risk",
            "id": "risk-1",
        }
    )
    assert h["risk_kind"] == "knockout_causal"
    assert h["risk_severity"] == "blocking"
    assert "desechamiento" in h["risk_reason_ux"].lower()


def test_build_forensic_risks_v1_from_causales():
    causales = [
        {"isRisk": True, "category": "risk", "texto": "Causa A", "id": "r1"},
        {"isRisk": True, "category": "economic", "texto": "Alerta B", "id": "e1"},
        {"isRisk": False, "category": "compliance", "texto": "Normal"},
    ]
    block = build_forensic_risks_v1(causales)
    assert block["stats"]["total"] == 2
    assert block["stats"]["blocking"] == 1
    assert block["stats"]["high"] == 1


def test_enrich_economic_alert_with_subtype():
    h = enrich_risk_hallazgo(
        {
            "tipo": "💰 ALERTA ECONÓMICA",
            "texto": "El presupuesto debe ser de $1,000,000.00 o más",
            "isRisk": True,
            "category": "economic",
            "id": "econ-fp",
        }
    )
    assert h["alert_subtype"] == SUBTYPE_AMBIGUOUS_PRESUPUESTO
    assert h["risk_severity"] == "high"

    h2 = enrich_risk_hallazgo(
        {
            "tipo": "💰 ALERTA ECONÓMICA",
            "texto": "El presupuesto debe ser de $1,000,000.00 o más",
            "snippet": "El licitante deberá presentar propuesta económica no menor a $1,000,000.00",
            "isRisk": True,
            "category": "economic",
            "id": "econ-fp2",
        }
    )
    assert h2["alert_subtype"] == "offer_floor"
    assert h2["risk_severity"] == "blocking"


def test_risk_decisions_hitl_and_continue_gate():
    causales = [
        {"isRisk": True, "category": "risk", "texto": "Knockout", "id": "risk-k1"},
        {"isRisk": True, "category": "economic", "texto": "Alerta", "id": "econ-1"},
    ]
    block = build_forensic_risks_v1(causales)
    record = apply_risk_decision_updates(
        None,
        decision_updates=[{"risk_id": "econ-1", "status": "accepted", "user_note": "ok"}],
    )
    assert not can_continue_with_risks(block, record)
    record2 = apply_risk_decision_updates(
        record,
        decision_updates=[{"risk_id": "risk-k1", "status": "accepted"}],
    )
    assert can_continue_with_risks(block, record2)
    merged = merge_risk_decisions_into_items(block, record2)
    assert merged["decision_stats"]["accepted"] == 2


def test_attach_forensic_risks_sanitizes_bases_hints():
    dictamen = {
        "causales": [
            {
                "tipo": "💰 ALERTA ECONÓMICA",
                "texto": "[Bases] criterio_importe_minimo_o_plazo_inferior: $500,000.00 — revisar coherencia.",
                "isRisk": True,
                "category": "economic",
                "id": "econ-1",
            },
            {
                "tipo": "💰 ALERTA ECONÓMICA",
                "texto": "El presupuesto debe ser de $1,000,000.00 o más",
                "isRisk": True,
                "category": "economic",
                "id": "econ-2",
            },
        ],
        "riesgos": 2,
    }
    out = attach_forensic_risks_to_dictamen(dictamen)
    assert out["riesgos"] == 0
    assert out["forensic_risks_v1"]["stats"]["total"] == 0
    assert out["causales"][0]["isRisk"] is False
    assert out["causales"][1]["isRisk"] is False


def test_attach_forensic_risks_to_dictamen():
    dictamen = {
        "causales": [
            {"isRisk": True, "category": "risk", "texto": "X", "id": "r1"},
        ],
        "riesgos": 0,
    }
    out = attach_forensic_risks_to_dictamen(dictamen)
    assert out["riesgos"] == 1
    assert out["forensic_risks_v1"]["stats"]["total"] == 1
