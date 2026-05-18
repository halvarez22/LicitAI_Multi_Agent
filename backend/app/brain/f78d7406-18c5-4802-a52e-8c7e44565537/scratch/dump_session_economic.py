import asyncio
import os
import json
from app.api.deps import get_connected_memory

async def dump_session_state(session_id: str):
    repo = await get_connected_memory()
    try:
        state = await repo.get_session(session_id)
        if not state:
            print(f"No se encontró la sesión: {session_id}")
            return
        
        print(f"--- DUMP DE SESIÓN: {session_id} ---")
        
        # 1. Sugerencias no verificadas (La fuente de la verdad para el mapeo)
        suggestions = state.get("economic_unverified_suggestions", [])
        print("\n[economic_unverified_suggestions]:")
        for s in suggestions:
            print(f"  - Field: {s.get('field')} | Label: {s.get('label') or s.get('concepto')}")
            
        # 2. Bloqueos actuales
        pending = state.get("pending_questions", [])
        print("\n[pending_questions (blocking)]: ")
        for q in pending:
            items = q.get("blocking_items", [])
            for it in items:
                 print(f"  - Concepto: {it.get('concepto_label')} | Field: {it.get('field')}")
                 
        # 3. Datos ya capturados
        inputs = state.get("economic_user_inputs", {})
        print("\n[economic_user_inputs actuales]:")
        print(json.dumps(inputs, indent=2))

    finally:
        await repo.disconnect()

if __name__ == "__main__":
    # Suponemos la sesión actual por los logs, si es otra, el usuario nos dirá
    target_session = "limpieza_isapeg" 
    asyncio.run(dump_session_state(target_session))
