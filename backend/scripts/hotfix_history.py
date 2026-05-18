import asyncio
import os
import re
from dotenv import load_dotenv
load_dotenv("backend/.env")
from app.api.deps import get_connected_memory

async def hotfix_history():
    repo = await get_connected_memory()
    try:
        sessions = await repo.list_sessions()
        if not sessions:
            return
            
        sessions.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        sid = sessions[0]["id"]
        print(f"Auditing session: {sid}")
        
        history = await repo.get_conversation(sid)
        if not history:
            print("No history found.")
            return
            
        changed = False
        for i, msg in enumerate(history):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                print(f"Msg {i}: {content[:50]}...")
                
                # Búsqueda más flexible
                if "brecha" in content.lower() or "seguridad operativa" in content.lower():
                    # REEMPLAZO TOTAL por algo humano
                    new_content = "¿Qué medidas de seguridad operativa manejas para este proyecto? Necesito ese detalle para completar tu propuesta."
                    
                    if new_content != content:
                        print(f"  -> Fixing Msg {i}")
                        msg["content"] = new_content
                        changed = True
        
        if changed:
            print(f"  [HOTFIX] Sesión {sid}: Historial actualizado.")
            await repo.save_conversation(sid, history)
        else:
            print(f"  [DONE] Nada que corregir en {sid}.")
                
    finally:
        await repo.disconnect()

if __name__ == "__main__":
    asyncio.run(hotfix_history())
