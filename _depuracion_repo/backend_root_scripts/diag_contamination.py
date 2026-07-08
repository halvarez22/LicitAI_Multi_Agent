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
    print(f"TENDER FILE: {s.get('tender_file_name')}")
    print(f"TENDER PATH: {s.get('tender_file_path')}")
    
    # Check if we have the master compliance list
    tasks = s.get("tasks_completed") or []
    has_compliance = any(t.get("task") == "master_compliance_list" for t in tasks)
    print(f"HAS COMPLIANCE: {has_compliance}")
    
    if has_compliance:
        for t in reversed(tasks):
            if t.get("task") == "master_compliance_list":
                data = t.get("result", {}).get("data", {})
                # Look at a sample name to identify the tender
                admin = data.get("administrativo") or []
                if admin:
                    print(f"SAMPLE ITEM: {admin[0].get('nombre')}")
                break
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
