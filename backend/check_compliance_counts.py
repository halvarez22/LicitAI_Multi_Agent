import asyncio
import sys
import json

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
    dictamen = session.get("dictamen", {})
    
    print(f"Total Requisitos (dictamen): {dictamen.get('totalRequisitos')}")
    print(f"Causales Count: {len(dictamen.get('causales', []))}")
    
    # Check compliance categories
    compliance = session.get("execution_results", {}).get("compliance", {})
    if not compliance:
        # Check tasks_completed
        tasks = session.get("tasks_completed", [])
        for t in reversed(tasks):
            if t.get("task") == "stage_completed:compliance":
                compliance = t.get("result", {})
                break
    
    comp_data = compliance.get("data", {})
    for cat in ("administrativo", "tecnico", "formatos"):
        items = comp_data.get(cat, [])
        print(f"Compliance {cat}: {len(items)} items")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
