from fastapi import APIRouter
from app.api.schemas.requests import ChatbotRequest
from app.api.schemas.responses import ChatbotResponse
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager
from app.api.deps import get_connected_memory
from app.contracts.agent_contracts import AgentInput

router = APIRouter()

@router.post("/ask", response_model=ChatbotResponse)
async def ask_chatbot(request: ChatbotRequest):
    """
    Habla con el Asistente Experto (RAG). Busca citas en los documentos subidos
    a través de VectorDB y mantiene un historial conversacional.
    """
    memory = await get_connected_memory()
    
    mcp_manager = MCPContextManager(memory_repository=memory)
    rag_agent = ChatbotRAGAgent(context_manager=mcp_manager)
    
    try:
        agent_input = AgentInput(
            session_id=request.session_id,
            company_id=request.company_id,
            company_data={"query": request.query},
            mode="full",
        )
        result = await rag_agent.process(agent_input)
        reply_data = result.data if result.data is not None else {}
        
        return ChatbotResponse(
            reply=reply_data.get("respuesta", "Lo siento, hubo un error de contexto."),
            citations=reply_data.get("citas", []),
            confidence=reply_data.get("confianza", "Baja"),
            expert_suggestion=reply_data.get("sugerencia"),
            data=reply_data
        )
    finally:
        await memory.disconnect()
