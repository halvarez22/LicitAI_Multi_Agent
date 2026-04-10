import pytest
from unittest.mock import AsyncMock, patch
from app.agents.economic import EconomicAgent
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse

def _memory_stub(company=None, session=None):
    mem = AsyncMock()
    mem.get_company = AsyncMock(return_value=company)
    mem.save_company = AsyncMock(return_value=True)
    mem.get_session = AsyncMock(return_value=session or {})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_conversation = AsyncMock(return_value=[])
    mem.save_conversation = AsyncMock(return_value=True)
    mem.record_task_completion = AsyncMock()
    return mem

async def _make_agent(mem):
    ctx = MCPContextManager(mem)
    ctx.get_global_context = AsyncMock(return_value={
        "session_id": "sess_econ",
        "session_state": await mem.get_session("sess_econ"),
        "compliance_master_list": (await mem.get_session("sess_econ")).get("master_compliance_list")
    })
    return EconomicAgent(ctx)

@pytest.mark.asyncio
async def test_economic_intake_flow_hito6():
    """Hito 6: Verifica el flujo completo de detección e intake de precios."""
    
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
    econ_agent = await _make_agent(mem)
    chatbot = ChatbotRAGAgent(MCPContextManager(mem))

    # 2. El Agente Económico debe detectar el gap y guardar la pregunta
    inp1 = AgentInput(session_id="sess_econ", company_id="co_econ")
    with patch.object(econ_agent.llm, "generate", AsyncMock(return_value=LLMResponse(
        success=True,
        response='{"items": [{"concepto": "Suministro de Laptop", "status": "price_missing"}]}'
    ))):
        res = await econ_agent.process(inp1)
    
    assert res.status == AgentStatus.WAITING_FOR_DATA
    assert "missing" in res.data
    assert res.data["missing"][0]["type"] == "economic_price"

    # 3. El Chatbot recibe la respuesta del usuario (ej: "15000")
    pending_questions = mem.save_session.call_args[0][1]["pending_questions"]
    
    # Simular entrada de usuario al chatbot
    with patch.object(chatbot.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="15000"))):
        chat_res = await chatbot._handle_data_intake(
            "sess_econ", "Cuesta 15,000 pesos", "co_econ",
            pending_questions, 0, mem.save_session.call_args[0][1]
        )

    # 4. Validar que se guardó en el CATÁLOGO
    mem.save_company.assert_called()
    saved_company = mem.save_company.call_args[0][1]
    assert len(saved_company["catalog"]) > 0
    assert saved_company["catalog"][0]["price_base"] == 15000.0
    
    # 5. Segunda corrida del Agente Económico
    inp2 = AgentInput(session_id="sess_econ", company_id="co_econ")
    with patch.object(mem, "get_company", AsyncMock(return_value=saved_company)):
        # Re-mock context with updated session data
        econ_agent_2 = await _make_agent(mem)
        with patch.object(econ_agent_2.llm, "generate", AsyncMock(return_value=LLMResponse(
            success=True,
            response='{"items": [{"concepto": "Suministro de Laptop", "precio_unitario": 15000.0, "subtotal": 15000.0, "status": "matched"}]}'
        ))):
            res2 = await econ_agent_2.process(inp2)
    
    assert res2.status == AgentStatus.SUCCESS
    assert res2.data["total_base"] == 15000.0
