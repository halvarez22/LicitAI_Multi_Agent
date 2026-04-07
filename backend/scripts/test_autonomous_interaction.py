"""
Laboratorio Entregable 1: DataGap -> pending_questions -> Chatbot -> master_profile.

Requisitos: DATABASE_URL (Postgres). Opcional: LLM_URL / VECTOR_DB_URL si RAG/inferencia
de DataGap o clasificación del chatbot los necesitan.

Sin emojis en salida: compatible con consolas Windows (cp1252).
"""
import asyncio
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

try:
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.agents.mcp_context import MCPContextManager
    from app.memory.factory import MemoryAdapterFactory
    from app.contracts.agent_contracts import AgentInput
except ImportError as e:
    print(f"[ERROR] Importacion: {e}")
    sys.exit(1)


async def run_test() -> None:
    print("\n[LicitAI TEST] Entregable 1: interaccion autonoma (DataGap + chatbot)\n")

    memory_repo = MemoryAdapterFactory.create_adapter()
    if memory_repo is None:
        print("[ERROR] MemoryAdapterFactory.create_adapter() devolvio None (DATABASE_URL?).")
        sys.exit(1)
    ok = await memory_repo.connect()
    if not ok:
        print("[ERROR] No se pudo conectar al backend de memoria.")
        sys.exit(1)
    
    # MCPContextManager requiere el repo en el constructor
    ctx = MCPContextManager(memory_repo)
    bot = ChatbotRAGAgent(ctx)
    
    sid = "interaction_demo_v2"
    cid = "co_autonomous_demo_v2"
    
    # 1. EMPRESA CON PERFIL INCOMPLETO
    company = {
        "id": cid,
        "name": "Demo Gen V2 S.A.",
        "master_profile": {
            "razon_social": "Demo Gen V2 S.A.",
            "rfc": None, # <--- GAP CRÍTICO
            "domicilio_fiscal": "Av. Reforma 123",
            "representante_legal": "Elena Gomez"
        }
    }
    await memory_repo.save_company(cid, company)
    await memory_repo.save_session(sid, {"id": sid, "tasks_completed": []})

    # 2. PROBAR DATA GAP (El primer escalón de la IA Autónoma)
    from app.agents.data_gap import DataGapAgent
    print("[1] Ejecutando DataGap para detectar brechas...")
    gap_agent = DataGapAgent(ctx)
    gap_res = await gap_agent.process(AgentInput(session_id=sid, company_id=cid, company_data=company))
    
    print(f"    - Status DataGap: {gap_res.status}")
    
    # 3. VERIFICAR PREGUNTAS PENDIENTES EN DB
    state = await memory_repo.get_session(sid)
    pending = state.get("pending_questions", [])
    if pending:
        print(f"    - OK Preguntas generadas: {[q.get('label') for q in pending]}")
    else:
        print("    - FAIL: No se detectaron brechas (pending_questions vacio).")
        await memory_repo.disconnect()
        return

    # 4. CHATBOT CONSUME LOS GAP (MODO PROACTIVO)
    print("\n[2] Simulando Chatbot proactivo (Inyectando gap proactivamente)...")
    # Entrada vacia permite al Chatbot buscar en pending_questions
    bot_in_empty = AgentInput(session_id=sid, company_id=cid, company_data={"query": ""})
    bot_res = await bot.process(bot_in_empty)
    print(f"    - Chatbot dice: {bot_res.data.get('respuesta')}")

    # 5. USUARIO CONTESTA AL CHATBOT
    user_rfc = "TSTR800101XYZ"
    print(f"\n[3] Usuario responde al Chatbot: 'Mi RFC es {user_rfc}'")
    bot_in_data = AgentInput(session_id=sid, company_id=cid, company_data={"query": f"Mí rfc es {user_rfc}"})
    bot_res_data = await bot.process(bot_in_data)
    print(f"    - Chatbot confirma guardado: {bot_res_data.data.get('respuesta')}")

    # 6. VERIFICAR PERSISTENCIA FINAL
    updated_co = await memory_repo.get_company(cid)
    final_rfc = updated_co.get("master_profile", {}).get("rfc")
    print(f"\n[4] Datos en Master Profile tras interacción: RFC = {final_rfc}")

    if final_rfc == user_rfc:
        print("\n[OK] Entregable 1: DataGap -> Chatbot -> master_profile (RFC persistido).")
    else:
        print(f"\n[FAIL] RFC no coincide. Esperado {user_rfc!r}, actual {final_rfc!r}")

    await memory_repo.disconnect()

if __name__ == "__main__":
    asyncio.run(run_test())
