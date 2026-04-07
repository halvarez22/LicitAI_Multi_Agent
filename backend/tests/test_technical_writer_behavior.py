"""
TechnicalWriterAgent: contrato de entrada/salida y ramas sin llamar a Ollama.
LLM y VectorDB mockeados; no se escribe en disco real.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.mcp_context import MCPContextManager
from app.agents.technical_writer import TechnicalWriterAgent


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
    # Mockear LLM y VectorDB desde el constructor (ahora instanciados ahí)
    agent.llm = AsyncMock()
    agent.llm.generate = AsyncMock(return_value={"response": "Contenido generado por mock."})
    agent.vector_db = MagicMock()
    agent.vector_db.query_texts = MagicMock(return_value={"documents": []})
    return agent


@pytest.mark.asyncio
async def test_sin_requisitos_tecnicos_devuelve_success_sin_archivos():
    """Sin ítems técnicos en compliance_data → success sin documentos."""
    agent = _make_agent()

    input_data = {
        "company_data": {"master_profile": {"razon_social": "Test Co", "rfc": "TST010101AAA"}},
        "compliance_master_list": {"tecnico": [], "administrativo": []},
    }

    with patch("os.makedirs"):
        out = await agent.process("sess_t1", input_data)

    assert out["status"] == "success"
    assert "No hay" in out.get("message", "")
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_con_requisitos_tecnicos_llm_es_invocado_y_devuelve_success():
    """Con ítems técnicos → LLM es invocado y se retorna success con documentos."""
    agent = _make_agent()

    req = {"id": "2.1", "nombre": "Capacidad Técnica", "descripcion": "Doc que acredite experiencia", "tipo": "tecnico"}
    input_data = {
        "company_data": {"master_profile": {"razon_social": "Test Co", "rfc": "TST010101AAA", "representante_legal": "Juan Test"}},
        "compliance_master_list": {"tecnico": [req]},
    }

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx") as mock_save, \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process("sess_t2", input_data)

    assert out["status"] == "success"
    assert "data" in out
    assert len(out["data"]["documentos"]) >= 2   # Carta + al menos 1 req
    # LLM invocado al menos una vez (carta de presentacion + req)
    assert agent.llm.generate.await_count >= 2


@pytest.mark.asyncio
async def test_fallback_compliance_desde_results_orquestador():
    """Si no hay compliance_master_list, debe leer de results.compliance.data."""
    agent = _make_agent()

    req = {"id": "2.2", "nombre": "Experiencia Previa", "descripcion": "Acreditar contratos previos", "tipo": "tecnico"}
    input_data = {
        "company_data": {"master_profile": {"razon_social": "Fallback Corp", "rfc": "FAL010101BBB"}},
        # Sin compliance_master_list explícito; viene en results (path del orquestador)
        "results": {"compliance": {"data": {"tecnico": [req]}}},
    }

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"), \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process("sess_t3", input_data)

    assert out["status"] == "success"
    assert len(out["data"]["documentos"]) >= 2
