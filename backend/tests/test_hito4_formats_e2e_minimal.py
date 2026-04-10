"""
E2E mínimo Hito 4 (dato realista en dict, sin MagicMock de negocio).

Ejecuta dos pasadas sobre FormatsAgent: bloqueo → perfil completado → éxito.
No requiere API HTTP ni Docker; valida contrato resume-ready del piloto.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.formats import FormatsAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse

# Perfil mínimo anónimo pero con forma real (México): RFC 12–13 chars, domicilio textual.
_PROFILE_INCOMPLETE = {
    "razon_social": "Empresa Demostrativa S.A. de C.V.",
    "tipo": "moral",
}
_PROFILE_COMPLETE = {
    **_PROFILE_INCOMPLETE,
    "rfc": "EDM850101ABC",
    "domicilio_fiscal": "Insurgentes Sur 1602, Crédito Constructor, Ciudad de México, CDMX, 03940",
    "representante_legal": "María Fernanda López Hernández",
}

_REQ = {
    "id": "1_1",
    "nombre": "Carta bajo protesta",
    "descripcion": "Declaración bajo protesta de decir verdad",
    "tipo": "administrativo",
}


def _memory_with_session(initial: dict):
    mem = AsyncMock()
    state = dict(initial)

    async def get_sess(_sid):
        return dict(state)

    async def save_sess(_sid, data):
        state.update(data)
        return True

    mem.get_session = AsyncMock(side_effect=get_sess)
    mem.save_session = AsyncMock(side_effect=save_sess)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem, state


@pytest.mark.asyncio
async def test_hito4_two_phase_block_then_generate_minimal_e2e():
    mem, state = _memory_with_session(
        {
            "name": "sess_hito4_e2e",
            "tasks_completed": [],
            "schema_version": 1,
        }
    )
    ctx = MCPContextManager(mem)
    agent = FormatsAgent(ctx)
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="Contenido legal de carta bajo protesta.\nSegundo párrafo.")
    )

    inp_block = AgentInput(
        session_id="sess_hito4_e2e",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": _PROFILE_INCOMPLETE,
            "compliance_master_list": {"administrativo": [_REQ], "formatos": []},
        },
        job_id="job_hito4_demo",
    )

    out1 = await agent.process(inp_block)
    assert out1.status == AgentStatus.WAITING_FOR_DATA
    assert out1.data.get("missing")
    assert all(m.get("type") == "profile_field" for m in out1.data["missing"])
    assert any(m.get("blocking_job_id") == "job_hito4_demo" for m in out1.data["missing"])

    # Simula ingesta vía chat / PUT empresa: el orquestador reinyectaría master_profile completo
    inp_ok = AgentInput(
        session_id="sess_hito4_e2e",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": _PROFILE_COMPLETE,
            "compliance_master_list": {"administrativo": [_REQ], "formatos": []},
        },
        job_id="job_hito4_demo",
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out2 = await agent.process(inp_ok)

    assert out2.status == AgentStatus.SUCCESS
    assert out2.data.get("count") == 1
    agent.llm.generate.assert_awaited_once()
