"""Tests de hidratación HRU de evidencia forense."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.forensic_risk_evidence_enrichment_service import (
    hydrate_forensic_risk_item_evidence,
    hydrate_forensic_risks_block,
)
from app.services.forensic_risk_service import attach_and_hydrate_forensic_risks

PRESUPUESTO_LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"


@pytest.mark.asyncio
async def test_hydrate_item_adds_evidence_v1_and_subtype():
    item = {
        "texto": PRESUPUESTO_LITERAL,
        "risk_id": "econ-test-1",
        "category": "economic",
    }
    mock_ev = {
        "page": 30,
        "snippet": "propuesta económica no menor a $1,000,000.00",
        "match_confidence": "alta",
        "provenance": "index_scan",
        "source": "bases.pdf",
    }
    with patch(
        "app.services.forensic_risk_evidence_service.resolve_forensic_risk_evidence",
        new_callable=AsyncMock,
        return_value=mock_ev,
    ):
        out = await hydrate_forensic_risk_item_evidence("sess-uat", item)

    assert out.get("evidence_v1", {}).get("evidence_mode") == "index_verified"
    assert out.get("page") == 30
    assert out.get("alert_subtype")
    assert out.get("risk_reason_ux")
    assert "presupuesto" in out.get("risk_reason_ux", "").lower() or "oferta" in out.get("risk_reason_ux", "").lower()


@pytest.mark.asyncio
async def test_hydrate_block_sets_evidence_hydrated_flag():
    block = {
        "schema_version": "forensic_risks_v1",
        "items": [{"texto": PRESUPUESTO_LITERAL, "risk_id": "r1"}],
    }
    with patch(
        "app.services.forensic_risk_evidence_service.resolve_forensic_risk_evidence",
        new_callable=AsyncMock,
        return_value={"match_confidence": "none"},
    ):
        out = await hydrate_forensic_risks_block("sess-uat", block)

    assert out.get("evidence_hydrated") is True
    assert len(out.get("items") or []) == 1
    assert out["items"][0].get("evidence_v1", {}).get("evidence_mode") == "inference_only"


@pytest.mark.asyncio
async def test_attach_and_hydrate_dictamen():
    dictamen = {
        "causales": [
            {
                "tipo": "💰 ALERTA ECONÓMICA",
                "texto": PRESUPUESTO_LITERAL,
                "isRisk": True,
                "category": "economic",
                "id": "econ-1",
                "evidence_v1": {
                    "evidence_mode": "index_verified",
                    "page": 1,
                    "snippet": "propuesta no menor a $1,000,000.00",
                    "match_confidence": "alta",
                },
            }
        ],
    }
    with patch(
        "app.services.forensic_risk_evidence_service.resolve_forensic_risk_evidence",
        new_callable=AsyncMock,
        return_value={
            "page": 1,
            "snippet": "propuesta no menor a $1,000,000.00",
            "match_confidence": "alta",
        },
    ):
        out = await attach_and_hydrate_forensic_risks(dictamen, "sess-uat")

    block = out.get("forensic_risks_v1") or {}
    assert block.get("evidence_hydrated") is True
    assert block.get("items")[0].get("risk_reason_ux")
