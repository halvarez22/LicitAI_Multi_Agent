import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory
from app.services.document_candidate_list_service import build_candidate_document_list

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
    
    print(f"Testing build_candidate_document_list with data for {session_id}...")
    candidates = build_candidate_document_list(
        compliance_master_list=comp_data,
        require_human_confirmation=True,
        low_conf_threshold=0.7
    )
    
    clist = candidates.get("candidate_document_list", [])
    print(f"Result: {len(clist)} candidates found.")
    
    if len(clist) == 0:
        print("DEBUG: Why is it empty?")
        for cat in ("administrativo", "tecnico", "formatos"):
            items = comp_data.get(cat, [])
            if items:
                print(f" - Found {len(items)} in {cat}")
                item = items[0]
                print(f"   Sample item keys: {list(item.keys())}")
                print(f"   Sample item action: {item.get('tipo_accion')}")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
