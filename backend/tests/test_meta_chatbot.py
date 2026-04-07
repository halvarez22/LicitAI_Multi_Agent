import pytest
from unittest.mock import AsyncMock, patch
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager

@pytest.mark.asyncio
async def test_chatbot_meta_query_recognition_hito8():
    """Hito 8: Valida que el chatbot reconozca consultas sobre el estado y responda con 'meta-data'."""
    
    # 1. Simular sesión bloqueada por precios
    mock_session = {
        "last_orchestrator_decision": {
            "stop_reason": "MISSING_PRICES"
        },
        "pending_questions": [
            {"label": "Precio de Laptop"}
        ]
    }
    
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value=mock_session)
    mem.get_conversation = AsyncMock(return_value=[])
    
    ctx = MCPContextManager(mem)
    chatbot = ChatbotRAGAgent(ctx)

    # 2. Mockear clasificador para que detecte 'META'
    with patch.object(chatbot.llm, "generate", AsyncMock(return_value={"response": "META"})):
        # Primera llamada: Pregunta explícita
        res = await chatbot.process("sess_meta", {"query": "¿Por qué se detuvo el proceso?", "company_id": "co1"})
        
        # Validar respuesta
        assert res["data"]["tipo"] == "meta_answer"
        assert "conceptos sin precio" in res["data"]["respuesta"]
        assert "Precio de Laptop" in res["data"]["respuesta"]
        
        # Segunda llamada: Verificar que NO intenta hacer RAG (no debe llamar al vector_db)
        with patch.object(chatbot.vector_db, "query_texts") as mock_query:
            await chatbot.process("sess_meta", {"query": "¿Qué falta?", "company_id": "co1"})
            # No se llega a llamar a RAG si es META
            mock_query.assert_not_called()
