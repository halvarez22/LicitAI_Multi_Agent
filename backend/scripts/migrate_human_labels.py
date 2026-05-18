import asyncio
import re
import os
from typing import Dict, Any, List
from dotenv import load_dotenv
load_dotenv("backend/.env")

from app.api.deps import get_connected_memory
from app.agents.chatbot_rag import ChatbotRAGAgent

async def migrate():
    repo = await get_connected_memory()
    try:
        sessions = await repo.list_sessions()
        print(f"Encontradas {len(sessions)} sesiones para auditar.")
        
        for s_summary in sessions:
            sid = s_summary.get("id")
            if not sid: continue
            
            state = await repo.get_session(sid)
            if not state: continue
            
            pending = list(state.get("pending_questions") or [])
            if not pending: continue
            
            changed = False
            for q in pending:
                old_label = q.get("label")
                # Si el label es puramente numérico o tiene patrón técnico
                if not old_label or old_label.isdigit() or "." in str(old_label) or "_" in str(old_label):
                    raw_ref = q.get("label") or q.get("field_target") or q.get("field") or ""
                    new_label = ChatbotRAGAgent._humanize_field_target(str(raw_ref))
                    
                    if new_label != old_label:
                        q["label"] = new_label
                        changed = True
            
            if changed:
                print(f"  [FIXED] Sesión {sid}: Etiquetas humanizadas.")
                await repo.save_session(sid, state)
                
        print("Migración forense completada.")
    finally:
        await repo.disconnect()

if __name__ == "__main__":
    asyncio.run(migrate())
