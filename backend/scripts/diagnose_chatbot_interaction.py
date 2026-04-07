import asyncio
import os
import sys
import json

# Setup PYTHONPATH
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/licitaciones"
os.environ["LLM_URL"] = "http://localhost:11434"
os.environ["VECTOR_DB_URL"] = "http://localhost:8000"

from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory
from app.agents.chatbot_rag import ChatbotRAGAgent
from app.contracts.agent_contracts import AgentInput

async def diagnose_chatbot():
    print("🔍 [LicitAI QA] DIAGNÓSTICO DE INTERACCIÓN DEL CHATBOT\n")
    
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    sid = "licitacin_pblica_nacional_presencial__40004001-003-24_"
    cid = "co_1774286420505"
    
    # 1. VERIFICAR ESTADO DE LA SESIÓN
    session = await memory.get_session(sid)
    if not session:
        print(f"❌ Error: Sesión {sid} no encontrada.")
        return
        
    pending = session.get("pending_questions", [])
    print(f"📋 Preguntas Pendientes en Sesión: {len(pending)}")
    for p in pending:
        print(f"   - {p.get('label')}: {p.get('question')}")
    
    if not pending:
        print("⚠️ No hay preguntas pendientes. Simulando una falta de RFC para el diagnóstico...")
        pending = [{"field": "rfc", "label": "RFC de la Empresa", "question": "¿Cuál es el RFC oficial de tu representada?"}]
        session["pending_questions"] = pending
        await memory.save_session(sid, session)

    # 2. PROBAR EL CHATBOT (RAG AGENT)
    print("\n🤖 Consultando al Chatbot (MODO NORMAL)...")
    ctx = MCPContextManager(memory)
    rag_agent = ChatbotRAGAgent(ctx)
    
    # El usuario dice "Hola" o "¿Qué falta?"
    user_query = "Hola, quiero generar los documentos"
    print(f"👤 Usuario: {user_query}")
    
    agent_input = AgentInput(
        session_id=sid,
        company_id=cid,
        company_data={"query": user_query},
        mode="full"
    )
    
    res = await rag_agent.process(agent_input)
    reply = res.data.get("respuesta") if res.data else "ERROR"
    
    print(f"🤖 Chatbot responde: {reply}")
    
    if "RFC" in reply or "¿Cuál es el RFC?" in reply:
        print("\n✅ OK: El Chatbot es proactivo y pide el RFC.")
    else:
        print("\n❌ FALLO: El Chatbot ignoró los Gaps y dio una respuesta genérica o buscó en documentos.")

    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(diagnose_chatbot())
