import pytest
from unittest.mock import AsyncMock, patch
from app.agents.economic import EconomicAgent
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager

def _memory_stub(company=None, session=None):
    mem = AsyncMock()
    mem.get_company = AsyncMock(return_value=company)
    mem.save_company = AsyncMock(return_value=True)
    mem.get_session = AsyncMock(return_value=session or {})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_conversation = AsyncMock(return_value=[])
    mem.save_conversation = AsyncMock(return_value=True)
    return mem

@pytest.mark.asyncio
async def test_economic_intake_flow_hito6():
    """Hito 6: Verifica el flujo completo de detección e intake de precios."""
    
    # 1. Escenario: Empresa con catálogo vacío
    mock_company = {
        "id": "co_econ",
        "catalog": [] 
    }
    mock_session = {
        "master_compliance_list": {
            "tecnico": [{"id": "T1", "nombre": "Suministro de Laptop", "descripcion": "Core i7"}]
        }
    }
    
    mem = _memory_stub(mock_company, mock_session)
    ctx = MCPContextManager(mem)
    
    econ_agent = EconomicAgent(ctx)
    chatbot = ChatbotRAGAgent(ctx)

    # 2. El Agente Económico debe detectar el gap y guardar la pregunta
    # Mock LLM para el match (dice que falta precio)
    with patch.object(econ_agent.llm, "generate", AsyncMock(return_value={
        "response": '{"items": [{"concepto": "Suministro de Laptop", "status": "price_missing"}]}'
    })):
        res = await econ_agent.process("sess_econ", {"company_id": "co_econ"})
    
    assert res["status"] == "waiting_for_data"
    assert "missing" in res
    assert res["missing"][0]["type"] == "economic_price"

    # 3. El Chatbot recibe la respuesta del usuario (ej: "15000")
    pending_questions = mem.save_session.call_args[0][1]["pending_questions"]
    
    # Simular entrada de usuario al chatbot
    with patch.object(chatbot.llm, "generate", AsyncMock(return_value={"response": "15000"})):
        # Pasamos el contexto actualizado con las preguntas pendientes
        chat_res = await chatbot._handle_data_intake(
            "sess_econ", "Cuesta 15,000 pesos", "co_econ",
            pending_questions, 0, mem.save_session.call_args[0][1]
        )

    # 4. Validar que se guardó en el CATÁLOGO, no en el perfil
    mem.save_company.assert_called()
    saved_company = mem.save_company.call_args[0][1]
    assert len(saved_company["catalog"]) > 0
    assert saved_company["catalog"][0]["price_base"] == 15000.0
    assert "description" in saved_company["catalog"][0]
    
    # 5. Segunda corrida del Agente Económico: ahora debe tener éxito
    # Mock LLM para el match (esta vez encuentra el precio en el catálogo inyectado)
    econ_agent_2 = EconomicAgent(ctx) # Re-instanciar para limpiar estados si los hubiera
    with patch.object(econ_agent_2.llm, "generate", AsyncMock(return_value={
        "response": '{"items": [{"concepto": "Suministro de Laptop", "precio_unitario": 15000.0, "subtotal": 15000.0, "status": "matched"}]}'
    })):
        # Inyectamos la empresa actualizada
        with patch.object(mem, "get_company", AsyncMock(return_value=saved_company)):
            res2 = await econ_agent_2.process("sess_econ", {"company_id": "co_econ"})
    
    assert res2["status"] == "success"
    assert res2["data"]["total_base"] == 15000.0
