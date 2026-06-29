"""DataGap no debe preguntar anos_experiencia en sesiones de obra documental."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.data_gap import DataGapAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse


@pytest.mark.asyncio
async def test_datagap_skips_anos_experiencia_for_obra_barda():
    mock_company = {
        "id": "co_barda",
        "master_profile": {
            "razon_social": "CONSTRUCTORA INFRAESTRUCTURA NACIONAL, S.A. DE C.V.",
            "representante_legal": "Juan Pérez",
            "rfc": "CIN900101ABC",
            "domicilio_fiscal": "León, Gto.",
        },
    }
    session_state = {
        "name": "BARDA PRIMARIA LOPEZ RAYON",
        "triage_context": {"tender_category": "OBRA", "law": "LOPSRM"},
        "compliance_master_list": {
            "formatos": [
                {
                    "id": "req-exp",
                    "nombre": "Documentación que compruebe su experiencia y capacidad técnica",
                    "descripcion": "Anexo T-2 contratos vigentes",
                }
            ],
        },
        "compliance_slot_cache": {},
    }
    mem = AsyncMock()
    mem.get_company = AsyncMock(return_value=mock_company)
    mem.get_session = AsyncMock(return_value=session_state)
    mem.save_session = AsyncMock(return_value=True)
    mem.save_company = AsyncMock(return_value=True)

    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    with patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), patch.object(
        agent.slot_inferer,
        "infer_all",
        return_value=["company_experience_years"],
    ), patch.object(
        agent.llm,
        "generate",
        AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO")),
    ):
        result = await agent.process(
            AgentInput(session_id="barda_primaria_lopez_rayon", company_id="co_barda", company_data={})
        )

    missing = [m["field"] for m in (result.data.get("missing") or [])]
    assert "anos_experiencia" not in missing
    assert result.status == AgentStatus.SUCCESS
