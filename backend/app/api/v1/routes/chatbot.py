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
    
    # SANEAMIENTO GLOBAL EN LA PUERTA DE ENTRADA (Req Gemini v1.7)
    safe_session_id = request.session_id.strip().lower().replace("-", "_")
    
    try:
        agent_input = AgentInput(
            session_id=safe_session_id,
            company_id=request.company_id,
            company_data={"query": request.query},
            mode="full",
        )
        result = await rag_agent.process(agent_input)
        reply_data = result.data if result.data is not None else {}

        # Incluir go_no_go_result si fue recalculado en este turno (Req 6.2)
        # El ChatbotRAGAgent lo persiste en session_state tras cada dato guardado
        session_state = await memory.get_session(safe_session_id) or {}
        
        # FIX ARQUITECTÓNICO: Si el usuario ya firmó la carta responsiva (override), 
        # amordazamos el envío del semáforo para no resucitar el panel en la UI.
        go_no_go_override = session_state.get("go_no_go_override") or {}
        already_authorized = go_no_go_override.get("authorized_by") == "user"
        
        if not already_authorized:
            gng_result = session_state.get("go_no_go_result")
            if gng_result:
                reply_data = {**reply_data, "go_no_go_result": gng_result}

        return ChatbotResponse(
            reply=reply_data.get("respuesta", "Lo siento, hubo un error de contexto."),
            citations=reply_data.get("citas", []),
            confidence=reply_data.get("confianza", "Baja"),
            expert_suggestion=reply_data.get("sugerencia"),
            suggested_actions=[sa.model_dump() for sa in result.suggested_actions] if result.suggested_actions else [],
            data=reply_data
        )
    finally:
        await memory.disconnect()
