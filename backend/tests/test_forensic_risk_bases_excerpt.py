"""Tests HRU: párrafo completo desde índice vectorial (sin inventar texto)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.forensic_risk_bases_excerpt_service import (
    _extract_paragraph,
    fetch_bases_excerpt_v1,
)

PAGE_TEXT = (
    "Sección 4. Requisitos económicos.\n\n"
    "El licitante deberá presentar propuesta económica no menor a $1,000,000.00 MXN. "
    "Este monto es piso de oferta y no sustituye el presupuesto autorizado.\n\n"
    "Otros requisitos generales aplican conforme al anexo."
)
LITERAL = "El presupuesto debe ser de $1,000,000.00 o más"


def test_extract_paragraph_finds_full_block_around_amount():
    para = _extract_paragraph(PAGE_TEXT, LITERAL)
    assert "$1,000,000.00" in para
    assert "licitante" in para.lower()
    assert len(para) > 80


def test_fetch_bases_excerpt_from_indexed_page():
    async def _run():
        mock_vdb = MagicMock()
        mock_vdb.get_sources.return_value = ["bases.pdf"]
        mock_vdb.fetch_page_documents.return_value = [PAGE_TEXT]

        with patch(
            "app.services.forensic_risk_bases_excerpt_service.resolve_forensic_risk_evidence",
            new_callable=AsyncMock,
            return_value={"page": 30, "source": "bases.pdf", "match_confidence": "alta"},
        ), patch(
            "app.services.vector_service.VectorDbServiceClient",
            return_value=mock_vdb,
        ):
            out = await fetch_bases_excerpt_v1("sess-1", LITERAL)

        assert out["available"] is True
        assert out["page"] == 30
        assert "$1,000,000.00" in out["paragraph"]
        assert out["provenance_ui"]["source"] == "vector_index"

    asyncio.run(_run())


def test_fetch_bases_excerpt_unavailable_without_index():
    async def _run():
        with patch(
            "app.services.forensic_risk_bases_excerpt_service.resolve_forensic_risk_evidence",
            new_callable=AsyncMock,
            return_value={},
        ):
            out = await fetch_bases_excerpt_v1("sess-1", LITERAL)
        assert out["available"] is False
        assert out["reason"] == "page_not_indexed"

    asyncio.run(_run())
