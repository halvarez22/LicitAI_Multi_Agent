"""
TechnicalWriterAgent: contrato de entrada/salida y ramas sin llamar a Ollama.
LLM y VectorDB mockeados; no se escribe en disco real.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.mcp_context import MCPContextManager
from app.agents.technical_writer import TechnicalWriterAgent
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse


def _memory_stub(tasks: list | None = None):
    mem = AsyncMock()
    sess = {"tasks_completed": tasks or [], "name": "test_session"}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


def _make_agent(tasks=None):
    ctx = MCPContextManager(_memory_stub(tasks))
    agent = TechnicalWriterAgent(ctx)
    # Mockear LLM y VectorDB desde el constructor
    agent.llm = AsyncMock()
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="Contenido generado por mock."))
    agent.vector_db = MagicMock()
    agent.vector_db.query_texts = MagicMock(return_value={"documents": []})
    return agent


@pytest.mark.asyncio
async def test_sin_requisitos_tecnicos_devuelve_success_sin_archivos():
    """Sin ítems técnicos en compliance_data → success sin documentos."""
    agent = _make_agent()

    inp = AgentInput(
        session_id="sess_t1",
        company_data={"master_profile": {"razon_social": "Test Co", "rfc": "TST010101AAA"}},
        company_id="co-1",
        mode="generation_only"
    )
    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert "No hay" in out.message
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_con_requisitos_tecnicos_llm_es_invocado_y_devuelve_success():
    """Con ítems técnicos → LLM es invocado y se retorna success con documentos."""
    agent = _make_agent()

    req = {"id": "2.1", "nombre": "Capacidad Técnica", "descripcion": "Doc que acredite experiencia", "tipo": "tecnico"}
    inp = AgentInput(
        session_id="sess_t2",
        company_data={"master_profile": {"razon_social": "Test Co", "rfc": "TST010101AAA", "representante_legal": "Juan Test"}},
        company_id="co-1",
        mode="generation_only"
    )
    # Inyectar compliance master list en company_data como espera el orquestador
    inp.company_data["compliance_master_list"] = {"tecnico": [req]}

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx") as mock_save, \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert "data" in out.model_dump()
    assert len(out.data["documentos"]) >= 2   # Carta + al menos 1 req
    # LLM invocado al menos una vez (carta de presentacion + req)
    assert agent.llm.generate.call_count >= 2


@pytest.mark.asyncio
async def test_fallback_compliance_desde_results_orquestador():
    """Si no hay compliance_master_list, debe leer de results.compliance.data."""
    agent = _make_agent()

    req = {"id": "2.2", "nombre": "Experiencia Previa", "descripcion": "Acreditar contratos previos", "tipo": "tecnico"}
    inp = AgentInput(
        session_id="sess_t3",
        company_data={"master_profile": {"razon_social": "Fallback Corp", "rfc": "FAL010101BBB"}},
        company_id="co-1",
        mode="generation_only"
    )
    # Simular que el compliance ya ocurrió y está en la sesión
    tasks = [{"task": "stage_completed:compliance", "result": {"data": {"tecnico": [req]}}}]
    agent.context_manager.get_global_context = AsyncMock(return_value={"session_state": {"tasks_completed": tasks}})

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"), \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)
 
    assert out.status == AgentStatus.SUCCESS
    assert len(out.data["documentos"]) >= 2
