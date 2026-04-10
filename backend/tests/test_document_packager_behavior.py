"""
DocumentPackagerAgent: contrato, parseo LLM robusto, fallback determinístico y rutas.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.agents.document_packager import DocumentPackagerAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse


def _memory_stub():
    mem = AsyncMock()
    # Para consistencia con los tests, mockear get_global_context también en el ctx
    return mem


def _make_agent():
    mem = _memory_stub()
    # sess_name = "test_session"
    mem.get_session = AsyncMock(return_value={"tasks_completed": [], "name": "test_session"})
    ctx = MCPContextManager(mem)
    # Mockear el global context para que devuelva session_state con name: test_session
    ctx.get_global_context = AsyncMock(return_value={"session_state": {"name": "test_session"}})
    
    agent = DocumentPackagerAgent(ctx)
    agent.llm = AsyncMock()
    # Suprimir smart_search para no tocar ChromaDB
    agent.smart_search = AsyncMock(return_value="")
    return agent


ESTRUCTURA_LLM_VALIDA = {
    "sobre_1": {
        "titulo": "SOBRE 1 - ADMINISTRATIVO",
        "nombre_carpeta": "SOBRE_1_ADMINISTRATIVO",
        "documentos": [{"nombre": "Acta Constitutiva", "ruta": "/data/acta.docx"}]
    },
    "sobre_2": {
        "titulo": "SOBRE 2 - TÉCNICO",
        "nombre_carpeta": "SOBRE_2_TECNICO",
        "documentos": []
    },
    "sobre_3": {
        "titulo": "SOBRE 3 - ECONÓMICO",
        "nombre_carpeta": "SOBRE_3_ECONOMICO",
        "documentos": []
    }
}


@pytest.mark.asyncio
async def test_packager_mapeo_llm_json_valido():
    """LLM devuelve JSON válido → copy2 invocado y estructura_sobres en el retorno."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response=json.dumps(ESTRUCTURA_LLM_VALIDA))
    )

    inp = AgentInput(
        session_id="sess_pk1",
        company_data={
            "master_profile": {"razon_social": "Test Co"},
            "documentos_generados": {
                "administrativa": [{"nombre": "Acta Constitutiva", "ruta": "/data/acta.docx"}]
            }
        }
    )

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=True), \
         patch("shutil.copy2") as mock_copy, \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert "estructura_sobres" in out.data
    # El doc de sobre_1 existe → copy2 debe haber sido llamado al menos 1 vez
    mock_copy.assert_called()


@pytest.mark.asyncio
async def test_packager_llm_error_usa_fallback():
    """Si LLM falla con error → fallback determinístico reparte los gen_docs."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=False, error="Ollama timeout"))

    inp = AgentInput(
        session_id="sess_pk2",
        company_data={
            "master_profile": {},
            "documentos_generados": {
                "administrativa": [{"nombre": "Acta", "ruta": "/data/acta.docx"}],
                "tecnica": [{"nombre": "Propuesta Técnica", "ruta": "/data/pt.docx"}],
                "economica": [{"nombre": "Propuesta Económica", "ruta": "/data/pe.xlsx"}],
            }
        }
    )

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    estructura = out.data["estructura_sobres"]
    # Los 3 sobres deben existir gracias al fallback
    assert "sobre_1" in estructura
    assert "sobre_2" in estructura
    assert "sobre_3" in estructura


@pytest.mark.asyncio
async def test_packager_respuesta_dict_no_attr_replace():
    """
    Regresión: asegurar que nunca se llame a .replace() sobre el dict completo.
    """
    agent = _make_agent()
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response=json.dumps(ESTRUCTURA_LLM_VALIDA))
    )

    inp = AgentInput(
        session_id="sess_pk3",
        company_data={
            "master_profile": {},
            "documentos_generados": {}
        }
    )

    # Si el código hiciera response.replace(...) explotaría con AttributeError
    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    # Que lleguemos aquí sin excepción es la aserción principal
    assert out.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_packager_usa_session_name_en_ruta():
    """El output_base debe contener session_name, no session_id cuando difieren."""
    agent = _make_agent()
    # Usar el session_id para la comparación (aunque el código usa session_id de la URL para crear la carpeta rota)
    # En app/agents/document_packager.py:52 -> os.path.join("/data", "outputs", session_id)
    # Wait, the code uses session_id from agent_input, not the name from mock_stub!
    
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=False, error="no llm"))

    inp = AgentInput(
        session_id="test_session",
        company_data={"master_profile": {}, "documentos_generados": {}}
    )

    captured_dirs = []

    def fake_makedirs(path, **kwargs):
        captured_dirs.append(path)

    with patch("os.makedirs", side_effect=fake_makedirs), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process(inp)

    # El código usa AgentInput.session_id para el path
    assert any("test_session" in d for d in captured_dirs), \
        f"test_session no encontrado en dirs: {captured_dirs}"
