"""
DeliveryAgent: contrato, rutas session_name, firma de generate corregida y fallback.
"""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.delivery import DeliveryAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse


def _memory_stub():
    mem = AsyncMock()
    # session_name es 'test_session'
    mem.get_session = AsyncMock(return_value={"tasks_completed": [], "name": "test_session"})
    mem.save_session = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem


def _make_agent():
    ctx = MCPContextManager(_memory_stub())
    agent = DeliveryAgent(ctx)
    agent.llm = AsyncMock()
    # LLMResponse objects needed
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=json.dumps(GUIA_VALIDA)))
    agent.smart_search = AsyncMock(return_value="Contexto RAG de bases")
    return agent


GUIA_VALIDA = {
    "tipo": "ELECTRONICA",
    "portal_url": "https://compranet.hacienda.gob.mx",
    "portal_nombre": "CompraNet",
    "fecha_limite": "2024-12-31 10:00",
    "pasos": [{"paso": 1, "accion": "Ingresar", "detalle": "Entrar al portal"}],
    "checklist": [{"check": "Firma electrónica válida", "status": "pendiente"}],
    "alertas": ["Verificar conexión de internet"]
}


@pytest.mark.asyncio
async def test_delivery_proceso_exitoso_llm_valido():
    """Valida que el agente procesa correctamente una respuesta JSON válida del LLM y genera el PDF en la ruta correcta."""
    agent = _make_agent()
    inp = AgentInput(session_id="sess_del1")
    
    # Mockear os.makedirs y _generate_pdf_guide para no escribir realmente
    with patch("os.makedirs"), \
         patch.object(agent, "_generate_pdf_guide") as mock_pdf:
        
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["tipo_licitacion"] == "ELECTRONICA"
    assert "LOGISTICA_Y_GUIA_DE_ENTREGA.pdf" in out.data["guia_pdf"]
    # Verificar que se usó 'sess_del1' en la ruta del PDF
    assert "sess_del1" in out.data["guia_pdf"]
    mock_pdf.assert_called_once()


@pytest.mark.asyncio
async def test_delivery_usa_fallback_si_llm_falla_con_error():
    """Si el LLM devuelve error, debe aplicar el fallback determinístico."""
    agent = _make_agent()
    # Simular error de red/timeout
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=False, error="Ollama timeout"))

    inp = AgentInput(session_id="sess_del2")

    with patch("os.makedirs"), \
         patch.object(agent, "_generate_pdf_guide"):
        
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    # El fallback tiene este tipo específico
    assert out.data["tipo_licitacion"] == "DETERMINACIÓN_MANUAL_REQUERIDA"
    assert len(out.data["alertas"]) > 0
    assert "No se pudo determinar" in out.data["alertas"][0]


@pytest.mark.asyncio
async def test_delivery_usa_fallback_si_json_no_es_valido():
    """Si el LLM devuelve texto plano o JSON malformado, aplica el fallback."""
    agent = _make_agent()
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="Esta es una respuesta que no es JSON"))

    inp = AgentInput(session_id="sess_del3")

    with patch("os.makedirs"), \
         patch.object(agent, "_generate_pdf_guide"):
        
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["tipo_licitacion"] == "DETERMINACIÓN_MANUAL_REQUERIDA"


@pytest.mark.asyncio
async def test_delivery_limpia_markdown_fences():
    """Valida que el agente puede parsear JSON incluso si el LLM pone ```json."""
    agent = _make_agent()
    json_with_fences = f"```json\n{json.dumps(GUIA_VALIDA)}\n```"
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=json_with_fences))

    inp = AgentInput(session_id="sess_del4")

    with patch("os.makedirs"), \
         patch.object(agent, "_generate_pdf_guide"):
        
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["tipo_licitacion"] == "ELECTRONICA"
