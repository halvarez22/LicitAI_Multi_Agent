"""Tests HRU reglas_economicas_evidence_v1 y gate de promoción forense."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.economic_alert_classifier import (
    include_alert_in_forensic_risks,
    normalize_economic_alert,
)
from app.services.reglas_economicas_evidence_service import (
    build_forensic_alerts_from_evidence_block,
    check_semantic_promotion,
    classify_semantic_class,
)
from app.services.economic_risk_evidence_v1 import MODE_INDEX_VERIFIED, MODE_INFERENCE_ONLY

BARDA_REGlas = {
    "referencia_partidas_anexos_citados": "El presupuesto debe ser de $1,000,000.00 o más",
    "criterio_importe_minimo_o_plazo_inferior": "$500,000.00 y un plazo de 6 meses",
}


def test_phantom_1m_not_promoted_without_index_verified():
    norm = normalize_economic_alert("El presupuesto debe ser de $1,000,000.00 o más")
    assert norm["include_in_forensic_risks"] is False


def test_verified_alert_promoted_with_index_evidence():
    item = {
        "texto": "Propuesta económica no menor a $5,100,000.00 MXN",
        "alert_subtype": "offer_floor",
        "evidence_v1": {
            "evidence_mode": MODE_INDEX_VERIFIED,
            "page": 1,
            "snippet": "MONTOS DE OBRA EJECUTADA MÍNIMO A $5,100,000.00",
        },
    }
    assert include_alert_in_forensic_risks(item) is True


def test_experience_snippet_blocks_presupuesto_key_promotion():
    semantic = classify_semantic_class(
        "referencia_partidas_anexos_citados",
        "El presupuesto debe ser de $1,000,000.00 o más",
        "MONTOS DE OBRA EJECUTADA MÍNIMO A $5,100,000.00",
    )
    assert semantic == "experience_amount"
    ok, reason = check_semantic_promotion(
        "referencia_partidas_anexos_citados",
        semantic,
        MODE_INDEX_VERIFIED,
    )
    assert ok is False
    assert reason == "REGULA_SEMANTIC_MISMATCH"


def test_build_forensic_alerts_skips_non_eligible():
    block = {
        "items": {
            "referencia_partidas_anexos_citados": {
                "value": "El presupuesto debe ser de $1,000,000.00 o más",
                "promotion_eligible": False,
                "evidence_v1": {"evidence_mode": MODE_INFERENCE_ONLY},
            },
            "criterio_importe_minimo_o_plazo_inferior": {
                "value": "MONTOS DE OBRA EJECUTADA MÍNIMO A $5,100,000.00",
                "promotion_eligible": True,
                "alert_subtype": "offer_floor",
                "evidence_v1": {
                    "evidence_mode": MODE_INDEX_VERIFIED,
                    "page": 1,
                    "snippet": "MONTOS DE OBRA EJECUTADA MÍNIMO A $5,100,000.00",
                },
            },
        }
    }
    alerts = build_forensic_alerts_from_evidence_block(block)
    assert len(alerts) == 1
    assert "5,100,000" in alerts[0]["texto"]
    assert alerts[0]["evidence_v1"]["evidence_mode"] == MODE_INDEX_VERIFIED


@pytest.mark.asyncio
async def test_build_reglas_evidence_marks_phantom_as_inference():
    mock_ev = {"match_confidence": "none", "provenance": "index_scan"}
    with patch(
        "app.services.forensic_risk_evidence_service.resolve_forensic_risk_evidence",
        new_callable=AsyncMock,
        return_value=mock_ev,
    ):
        from app.services.reglas_economicas_evidence_service import (
            build_reglas_economicas_evidence_v1,
        )

        out = await build_reglas_economicas_evidence_v1("sess-x", BARDA_REGlas)
    item = out["items"]["referencia_partidas_anexos_citados"]
    assert item["promotion_eligible"] is False
    assert item["evidence_v1"]["evidence_mode"] == MODE_INFERENCE_ONLY
    assert out["stats"]["promotion_eligible"] == 0
