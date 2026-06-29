"""Tests: escaneo determinista del índice por monto."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.forensic_risk_bases_excerpt_service import fetch_bases_excerpt_v1
from app.services.forensic_risk_evidence_service import _scan_index_for_literal

LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"
PAGE30 = (
    "[FUENTE: bases.pdf | PÁGINA: 30]\n"
    "El licitante deberá presentar propuesta económica no menor a $1,000,000.00 MXN."
)


def test_scan_index_finds_amount_when_semantic_search_would_miss():
    vdb = MagicMock()
    vdb.scan_session_chunks.return_value = [
        (PAGE30, {"page": 30, "source": "bases.pdf"}),
    ]
    hit = _scan_index_for_literal(vdb, "sess", LITERAL)
    assert hit.get("page") == 30
    assert "$1,000,000.00" in str(hit.get("snippet") or "")


def test_fetch_excerpt_uses_index_scan_when_vector_empty():
    async def _run():
        mock_vdb = MagicMock()
        mock_vdb.count_session_chunks.return_value = 42
        mock_vdb.get_sources.return_value = ["bases.pdf"]
        mock_vdb.fetch_page_documents.return_value = [PAGE30.split("\n", 1)[1]]
        mock_vdb.scan_session_chunks.return_value = [
            (PAGE30, {"page": 30, "source": "bases.pdf"}),
        ]

        with patch(
            "app.services.forensic_risk_bases_excerpt_service.resolve_forensic_risk_evidence",
            new_callable=AsyncMock,
            return_value={},
        ), patch(
            "app.services.forensic_risk_bases_excerpt_service._ensure_index_ready",
            new_callable=AsyncMock,
        ), patch(
            "app.services.vector_service.VectorDbServiceClient",
            return_value=mock_vdb,
        ):
            out = await fetch_bases_excerpt_v1("sess-1", LITERAL)

        assert out["available"] is True
        assert out["page"] == 30
        assert "$1,000,000.00" in out["paragraph"]

    asyncio.run(_run())
