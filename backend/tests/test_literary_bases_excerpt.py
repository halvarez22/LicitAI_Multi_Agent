"""Excerpt HRU para citas literales rag_literal_*."""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.literary_bases_excerpt_service import fetch_literary_bases_excerpt_v1

LITERAL = (
    "La junta de aclaraciones se llevará el 10 de diciembre del año 2025 a las 10:30 hrs."
)


@pytest.mark.asyncio
async def test_fetch_literary_excerpt_missing_literal():
    out = await fetch_literary_bases_excerpt_v1("sess", {})
    assert out["available"] is False
    assert out["reason"] == "missing_session_or_literal"


@pytest.mark.asyncio
@patch(
    "app.services.literary_bases_excerpt_service.fetch_bases_excerpt_v1",
    new_callable=AsyncMock,
)
async def test_fetch_literary_excerpt_delegates_to_bases_excerpt(mock_fetch):
    expected = {
        "schema_version": "bases_excerpt_v1",
        "available": True,
        "literal": LITERAL,
        "page": 29,
        "paragraph": LITERAL,
    }
    mock_fetch.return_value = expected
    out = await fetch_literary_bases_excerpt_v1(
        "sess-1",
        {"literal": LITERAL, "page": 29, "source": "BASES.pdf"},
    )
    assert out["available"] is True
    assert out["page"] == 29
    mock_fetch.assert_awaited_once()


def test_sanitize_indexed_hru_text_strips_fuente_block():
    from app.services.forensic_risk_bases_excerpt_service import _sanitize_indexed_hru_text

    raw = (
        "[FUENTE: BASES.pdf | PÁGINA: 29]\n29\nDE LA JUNTA DE ACLARACIONES\n"
        "el día 10 de diciembre del año 2025 a las 10:30 hrs."
    )
    clean = _sanitize_indexed_hru_text(raw)
    assert "[FUENTE:" not in clean
    assert "DE LA JUNTA" in clean
    assert "10:30" in clean
