import asyncio
import sys
from pathlib import Path

sys.path.append(".")
from app.api.deps import get_connected_memory

async def check():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    s = await m.get_session(session_id)
    if not s:
        print(f"Session {session_id} not found")
        return
    
    print(f"SESSION ID: {session_id}")
    
    tasks = s.get("tasks_completed") or []
    for t in reversed(tasks):
        if t.get("task") == "master_compliance_list":
            data = t.get("result", {}).get("data", {})
            for zone in ("administrativo", "tecnico", "formatos"):
                print(f"\n--- ZONE: {zone} ---")
                items = data.get(zone) or []
                for it in items[:10]:
                    print(f"- {it.get('nombre')} | Snippet: {str(it.get('snippet'))[:60]}")
            break
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
