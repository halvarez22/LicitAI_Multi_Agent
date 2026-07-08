import asyncio
import sys
import json
from collections import Counter

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory

async def check():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    if not m:
        print("No DB connection")
        return
    
    session = await m.get_session(session_id)
    
    # Get compliance from tasks_completed
    compliance = {}
    tasks = session.get("tasks_completed", [])
    for t in reversed(tasks):
        if t.get("task") == "stage_completed:compliance":
            compliance = t.get("result", {})
            break
    
    comp_data = compliance.get("data", {})
    actions = []
    items_sampled = []
    
    for cat in ("administrativo", "tecnico", "formatos"):
        items = comp_data.get(cat, [])
        for item in items:
            action = item.get("tipo_accion", "missing")
            actions.append(action)
            if len(items_sampled) < 10:
                items_sampled.append({
                    "name": item.get("nombre") or item.get("descripcion"),
                    "action": action,
                    "cat": cat
                })
    
    print(f"Action Distribution: {Counter(actions)}")
    print("Sample items:")
    for it in items_sampled:
        print(f" - [{it['cat']}] {it['name'][:50]}... -> {it['action']}")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
