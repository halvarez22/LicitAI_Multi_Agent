import asyncio
import os
from dotenv import load_dotenv
load_dotenv("backend/.env")
from app.api.deps import get_connected_memory

async def dump_latest():
    repo = await get_connected_memory()
    try:
        sessions = await repo.list_sessions()
        if not sessions:
            print("No sessions found.")
            return
            
        # Ordenar por el que tenga más actividad o el último creado
        sessions.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        sid = sessions[0]["id"]
        
        state = await repo.get_session(sid)
        print(f"DEBUG - Session ID: {sid}")
        pending = state.get("pending_questions") or []
        print(f"DEBUG - Total pending: {len(pending)}")
        
        for i, q in enumerate(pending[:5]):
            print(f"Question {i+1}:")
            print(f"  Label: {q.get('label')}")
            print(f"  Field: {q.get('field_target')}")
            print(f"  Text:  {q.get('question')[:60]}...")
            
    finally:
        await repo.disconnect()

if __name__ == "__main__":
    asyncio.run(dump_latest())
