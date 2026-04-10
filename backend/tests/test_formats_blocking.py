import pytest
from unittest.mock import AsyncMock, patch

from app.agents.formats import FormatsAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus


def _memory_stub(session_state=None):
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value=session_state or {})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


@pytest.mark.asyncio
async def test_formats_blocking_when_slots_missing():
    """Hito 4: FormatsAgent bloquea si faltan slots críticos (sin escribir outputs)."""
    inp = AgentInput(
        session_id="sess_4",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {"razon_social": "Test S.A."},
            "compliance_master_list": {
                "administrativo": [{"id": "1_1", "nombre": "Carta A", "tipo": "administrativo"}],
                "formatos": [],
            },
        },
        job_id="job_fmt_block",
    )

    mem = _memory_stub(session_state={"name": "sess_4", "schema_version": 1})
    ctx = MCPContextManager(mem)
    agent = FormatsAgent(ctx)

    out = await agent.process(inp)

    assert out.status == AgentStatus.WAITING_FOR_DATA
    missing = out.data.get("missing") or []
    fields = [m["field"] for m in missing]
    assert "rfc" in fields
    assert "domicilio_fiscal" in fields
    assert "representante_legal" in fields
    assert all(m.get("type") == "profile_field" for m in missing)
    assert all(m.get("blocking_job_id") == "job_fmt_block" for m in missing)

    assert mem.save_session.called
    last_save = mem.save_session.call_args[0][1]
    assert "pending_questions" in last_save
    assert len(last_save["pending_questions"]) == 3


@pytest.mark.asyncio
async def test_formats_proceeds_when_slots_complete():
    """Hito 4: con slots presentes continúa la generación (LLM mockeado)."""
    from app.services.resilient_llm import LLMResponse

    inp = AgentInput(
        session_id="sess_4_ok",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test S.A.",
                "rfc": "ABC123456XYZ",
                "domicilio_fiscal": "Calle Falsa 123",
                "representante_legal": "Juan Pérez",
            },
            "compliance_master_list": {
                "administrativo": [{"id": "1_1", "nombre": "Carta A", "tipo": "administrativo"}],
                "formatos": [],
            },
        },
    )

    mem = _memory_stub(session_state={"name": "sess_4_ok", "schema_version": 1})
    ctx = MCPContextManager(mem)
    agent = FormatsAgent(ctx)
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="Contenido Legal")
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data.get("count") == 1
