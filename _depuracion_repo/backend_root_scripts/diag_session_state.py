import asyncio
import json
import os
from app.memory.factory import MemoryAdapterFactory
from app.agents.mcp_context import MCPContextManager
from app.core.logging_config import get_logger

logger = get_logger("diag_session")

async def diag():
    adapter = MemoryAdapterFactory.create_adapter()
    if not adapter:
        print("Error creando adaptador.")
        return
    
    await adapter.connect()
    
    sessions = await adapter.list_sessions()
    if not sessions:
        print("No se encontraron sesiones.")
        await adapter.disconnect()
        return

    print(f"Encontradas {len(sessions)} sesiones.")
    # El más reciente según list_sessions (order_by updated_at desc)
    s_info = sessions[0]
    session_id = s_info.get("id")
    print(f"--- DIAGNÓSTICO DE SESIÓN: {session_id} ({s_info.get('display_name')}) ---")
    
    state = await adapter.get_session(session_id)
    if not state:
        print("No hay estado para esta sesión.")
        await adapter.disconnect()
        return

    # 1. Ver inputs de usuario
    inputs = state.get("economic_user_inputs", {})
    print("\n[USER INPUTS]")
    cp = inputs.get("concept_prices", {})
    print(f"Concept Prices (Dict): {json.dumps(cp, indent=2)}")
    print(f"Subtotal Propuesta: {inputs.get('subtotal_propuesta')}")

    # 2. Ver preguntas pendientes
    pending = state.get("pending_questions", [])
    print(f"\n[PENDING QUESTIONS] Total: {len(pending)}")
    for i, q in enumerate(pending):
        print(f"{i+1}. Type: {q.get('type')} | Label: {q.get('label')} | Field: {q.get('field')}")

    # 3. Ver tareas completadas (Economic Proposal)
    tasks = state.get("tasks_completed", [])
    for t in tasks:
        if t.get("task") == "economic_proposal":
            res = t.get("result", {})
            items = res.get("items", [])
            print(f"\n[ECONOMIC PROPOSAL TASK RESULT]")
            print(f"Total Base: {res.get('total_base')}")
            print(f"Items count: {len(items)}")
            for it in items[:10]: # Solo los primeros 10
                print(f"- {it.get('concepto')}: PU={it.get('precio_unitario')} | Status={it.get('status')} | ID={it.get('concepto_id')}")
            if len(items) > 10: print("...")

    await adapter.disconnect()

if __name__ == "__main__":
    asyncio.run(diag())
