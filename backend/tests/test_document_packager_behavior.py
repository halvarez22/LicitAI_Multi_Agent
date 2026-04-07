"""
DocumentPackagerAgent: contrato, parseo LLM robusto, fallback determinístico y rutas.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.agents.document_packager import DocumentPackagerAgent
from app.agents.mcp_context import MCPContextManager


def _memory_stub():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={"tasks_completed": [], "name": "test_session"})
    mem.save_session = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem


def _make_agent():
    ctx = MCPContextManager(_memory_stub())
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
        return_value={"response": json.dumps(ESTRUCTURA_LLM_VALIDA)}
    )

    input_data = {
        "company_data": {"master_profile": {"razon_social": "Test Co"}},
        "documentos_generados": {
            "administrativa": [{"nombre": "Acta Constitutiva", "ruta": "/data/acta.docx"}]
        }
    }

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=True), \
         patch("shutil.copy2") as mock_copy, \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process("sess_pk1", input_data)

    assert out["status"] == "success"
    assert "estructura_sobres" in out["data"]
    # El doc de sobre_1 existe → copy2 debe haber sido llamado al menos 1 vez
    mock_copy.assert_called()


@pytest.mark.asyncio
async def test_packager_llm_error_usa_fallback():
    """Si LLM falla con error → fallback determinístico reparte los gen_docs."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value={"error": "Ollama timeout"})

    input_data = {
        "company_data": {"master_profile": {}},
        "documentos_generados": {
            "administrativa": [{"nombre": "Acta", "ruta": "/data/acta.docx"}],
            "tecnica": [{"nombre": "Propuesta Técnica", "ruta": "/data/pt.docx"}],
            "economica": [{"nombre": "Propuesta Económica", "ruta": "/data/pe.xlsx"}],
        }
    }

    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process("sess_pk2", input_data)

    assert out["status"] == "success"
    estructura = out["data"]["estructura_sobres"]
    # Los 3 sobres deben existir gracias al fallback
    assert "sobre_1" in estructura
    assert "sobre_2" in estructura
    assert "sobre_3" in estructura


@pytest.mark.asyncio
async def test_packager_respuesta_dict_no_attr_replace():
    """
    Regresión: asegurar que nunca se llame a .replace() sobre el dict completo.
    El mock devuelve un dict (comportamiento real de LLMServiceClient) y no debe
    producir AttributeError → el test pasa si el agente no explota.
    """
    agent = _make_agent()
    # Devolvemos un dict con respuesta JSON correcta, igual que el cliente real
    agent.llm.generate = AsyncMock(
        return_value={"response": json.dumps(ESTRUCTURA_LLM_VALIDA), "context": []}
    )

    input_data = {
        "company_data": {"master_profile": {}},
        "documentos_generados": {}
    }

    # Si el código hiciera response.replace(...) explotaría con AttributeError
    with patch("os.makedirs"), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process("sess_pk3", input_data)

    # Que lleguemos aquí sin excepción es la aserción principal
    assert out["status"] == "success"


@pytest.mark.asyncio
async def test_packager_usa_session_name_en_ruta():
    """El output_base debe contener session_name, no session_id cuando difieren."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value={"error": "no llm"})

    input_data = {
        "company_data": {"master_profile": {}},
        "documentos_generados": {}
    }

    captured_dirs = []

    def fake_makedirs(path, **kwargs):
        captured_dirs.append(path)

    with patch("os.makedirs", side_effect=fake_makedirs), \
         patch("os.path.exists", return_value=False), \
         patch("shutil.copy2"), \
         patch.object(agent, "_generate_caratula"):
        out = await agent.process("sess_pk4", input_data)

    # "test_session" viene del _memory_stub → debe aparecer en las rutas creadas
    assert any("test_session" in d for d in captured_dirs), \
        f"session_name no encontrado en dirs: {captured_dirs}"
