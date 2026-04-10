import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse

@pytest.fixture
def mock_context():
    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    # Importante: AsyncMock por defecto retorna otro AsyncMock (que evalúa como coroutine)
    # Por eso establecemos return_value={} por defecto
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)
    ctx.memory.get_company = AsyncMock(return_value={"id": "c1", "master_profile": {}})
    ctx.memory.save_company = AsyncMock(return_value=True)
    ctx.memory.get_conversation = AsyncMock(return_value=[])
    ctx.memory.save_conversation = AsyncMock(return_value=True)
    return ctx

@pytest.fixture
def agent(mock_context):
    # Parchamos las clases de servicios para evitar conexiones HttpClient reales (ChromaDB/LLM)
    with patch("app.agents.chatbot_rag.VectorDbServiceClient") as mock_vector_class, \
         patch("app.agents.chatbot_rag.ResilientLLMClient") as mock_llm_class:
        
        a = ChatbotRAGAgent(mock_context)
        # Sincronizamos los mocks con las instancias que usa el agente
        a.llm = mock_llm_class.return_value
        a.llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response="QUERY")
        )
        a.llm.chat = AsyncMock(
            return_value=LLMResponse(success=True, response="respuesta RAG")
        )
        
        a.vector_db = mock_vector_class.return_value
        # get_sources NO es asíncrono en servicios/vector_service.py
        a.vector_db.get_sources = MagicMock(return_value=["bases.pdf"])
        a.vector_db.query_texts_filtered = MagicMock(return_value={"documents": [], "metadatas": []})
        a.vector_db.query_texts = MagicMock(return_value={"documents": [], "metadatas": []})
        
        return a


def _inp(session_id: str, query: str, company_id: str = "comp_1") -> AgentInput:
    return AgentInput(
        session_id=session_id,
        company_id=company_id,
        company_data={"query": query},
    )


@pytest.mark.asyncio
async def test_chatbot_proactivo_si_hay_preguntas(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [{"label": "RFC", "question": "¿Tu RFC?", "document_hint": "CIF"}],
        "current_question_index": 0
    }
    resp = await agent.process(_inp("sess_1", ""))
    assert resp.status == AgentStatus.SUCCESS
    assert "RFC" in resp.data["respuesta"]

@pytest.mark.asyncio
async def test_chatbot_modo_data_intake_y_persistencia(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [
            {"field": "rfc", "label": "RFC", "question": "¿Tu RFC?"},
            {"field": "tel", "label": "Teléfono", "question": "¿Tu tel?"}
        ],
        "current_question_index": 0
    }
    # La heurística rápida de Chatbot lo clasificará como DATA_INTAKE sin llamar a llm.generate
    # si el query tiene señales como 'mi '. Pero si usamos side_effect, debemos ser precisos.
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="ABC123456XYZ")
    )

    resp = await agent.process(_inp("sess_1", "mi rfc es ABC123456XYZ"))

    assert resp.status == AgentStatus.SUCCESS
    assert "RFC" in resp.data["respuesta"]
    assert "ABC123456XYZ" in resp.data["respuesta"]

@pytest.mark.asyncio
async def test_chatbot_modo_rag_query(agent, mock_context):
    # Forzamos modo QUERY vía LLM
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="QUERY")
    )
    agent.vector_db.query_texts_filtered.return_value = {
        "documents": ["Contexto de prueba."],
        "metadatas": [{"source": "bases.pdf", "page": 5}]
    }
    agent.llm.chat = AsyncMock(
        return_value=LLMResponse(success=True, response="Respuesta basada en Pág. 5")
    )

    resp = await agent.process(_inp("sess_1", "¿Como se paga?"))

    assert resp.status == AgentStatus.SUCCESS
    assert "rag_answer" in resp.data["tipo"]
    assert len(resp.data["citas"]) > 0

@pytest.mark.asyncio
async def test_chatbot_finaliza_flujo(agent, mock_context):
    mock_context.memory.get_session.return_value = {
        "pending_questions": [{"field": "tel", "label": "Teléfono", "question": "¿Tu tel?"}],
        "current_question_index": 0
    }
    # Activamos heurística rápida (último pendiente → mensaje de expediente completo)
    resp = await agent.process(_inp("sess_1", "mi tel es 555"))
    assert "expediente de sti ha sido recibido" in resp.data["respuesta"].lower()
