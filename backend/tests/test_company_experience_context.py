"""Tests para contexto de experiencia empresarial desde Fuentes."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.company_experience_context import (
    build_company_experience_context_block,
    req_needs_company_experience,
)


def test_req_needs_company_experience_te03():
    assert req_needs_company_experience("TE-03", "Propuesta técnica", "Relación de clientes")
    assert not req_needs_company_experience("TE-01", "Organigrama", "Estructura")


@pytest.mark.asyncio
async def test_build_company_experience_context_from_session_docs():
    memory = MagicMock()
    memory.get_documents = AsyncMock(
        return_value=[
            {
                "content": {
                    "filename": "referencias_clientes.pdf",
                    "status": "ANALYZED",
                    "extracted_text": (
                        "Constancia de contrato número XYZ-99 para servicio de mantenimiento "
                        "para las Unidades de este Organismo Contratante Demo."
                    ),
                }
            }
        ]
    )
    block = await build_company_experience_context_block(memory, "sess-1")
    assert "referencias_clientes.pdf" in block
    assert "EXPERIENCIA Y CONTRATOS PREVIOS" in block
