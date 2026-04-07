"""Matching difuso Excel ↔ requisitos en EconomicAgent._apply_tabular_prices_to_proposal."""
from unittest.mock import AsyncMock

import pytest

from app.agents.economic import EconomicAgent
from app.agents.mcp_context import MCPContextManager


def test_fuzzy_match_cierra_gap_cuando_subcadena_falla():
    ctx = MCPContextManager(AsyncMock())
    agent = EconomicAgent(ctx)
    proposal = [
        {
            "concepto": "Servicio integral de vigilancia perimetral armada las 24 horas",
            "concepto_id": "r1",
            "cantidad": 2,
            "precio_unitario": 0,
            "status": "price_missing",
        }
    ]
    tech = [{"id": "r1", "descripcion": "Requisito técnico genérico"}]
    rows = [
        {
            "concepto_norm": "vigilancia perimetral 24 hrs",
            "precio_unitario": 88.5,
        }
    ]
    out = agent._apply_tabular_prices_to_proposal(proposal, tech, rows)
    assert out[0]["status"] == "matched"
    assert out[0]["precio_unitario"] == 88.5
    assert out[0]["subtotal"] == pytest.approx(177.0)
    assert out[0]["price_source"] == "session_line_items_fuzzy"
    assert "tabular_match_score" in out[0]
    assert out[0]["tabular_match_score"] >= 0.68
