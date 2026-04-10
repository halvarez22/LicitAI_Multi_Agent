"""
FormatsAgent: contrato de entrada/salida, sin LLM real ni disco.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.formats import FormatsAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse

_SLOTS_PILOTO = {
    "domicilio_fiscal": "Av. Reforma 222, Col. Juárez, Ciudad de México",
    "representante_legal": "María Representante Legal",
}


def _memory_stub(tasks: list | None = None):
    mem = AsyncMock()
    sess = {"tasks_completed": tasks or [], "name": "test_sess", "schema_version": 1}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


def _make_agent(tasks=None):
    ctx = MCPContextManager(_memory_stub(tasks))
    agent = FormatsAgent(ctx)
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="Contenido legal mockeado.")
    )
    return agent


@pytest.mark.asyncio
async def test_sin_formatos_devuelve_success_vacio():
    agent = _make_agent()

    inp = AgentInput(
        session_id="sess_f1",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101AAA",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [], "formatos": []},
        },
    )

    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 0
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_con_formatos_llm_invocado_y_success():
    agent = _make_agent()

    req = {
        "id": "1.1",
        "nombre": "Acta Constitutiva",
        "descripcion": "Copia del acta",
        "tipo": "administrativo",
    }
    inp = AgentInput(
        session_id="sess_f2",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101BBB",
                "representante_legal": "Ana Test",
                "domicilio_fiscal": _SLOTS_PILOTO["domicilio_fiscal"],
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 1
    assert len(out.data["documentos"]) == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_compliance_desde_tasks_cuando_no_hay_inyeccion():
    """Sin compliance_master_list en company_data debe leer stage_completed:compliance."""
    compliance_payload = {
        "administrativo": [
            {
                "id": "1.2",
                "nombre": "Declaración Fiscal",
                "descripcion": "Últimas 3 declaraciones",
                "tipo": "administrativo",
            }
        ],
        "formatos": [],
    }
    tasks = [
        {
            "task": "stage_completed:compliance",
            "result": {"status": "success", "data": compliance_payload},
        }
    ]
    agent = _make_agent(tasks=tasks)

    inp = AgentInput(
        session_id="sess_f3",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Fallback SA",
                "rfc": "FAL010101CCC",
                **_SLOTS_PILOTO,
            },
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_error_no_genera_archivo_y_sigue():
    agent = _make_agent()
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=False, error="LLM timeout", response="")
    )

    req = {"id": "1.3", "nombre": "Carta Bajo Protesta", "tipo": "administrativo"}
    inp = AgentInput(
        session_id="sess_f4",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Err SA",
                "rfc": "ERR010101DDD",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx") as mock_save:
        out = await agent.process(inp)

    agent.llm.generate.assert_awaited_once()
    mock_save.assert_not_called()
    assert out.data["count"] == 0


@pytest.mark.asyncio
async def test_item_sin_prefijo_pero_tipo_administrativo_se_incluye():
    agent = _make_agent()

    req = {"id": "admin_003", "nombre": "Declaración de Integridad", "tipo": "administrativo"}
    inp = AgentInput(
        session_id="sess_f5",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Tipo SA",
                "rfc": "TIP010101EEE",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()
