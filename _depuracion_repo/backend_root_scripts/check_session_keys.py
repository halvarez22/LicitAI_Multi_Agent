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
    if not session:
        print(f"Session not found: {session_id}")
        return
    
    print(f"--- SESSION TOP-LEVEL KEYS FOR {session_id} ---")
    print(f"Keys: {list(session.keys())}")
    
    if "document_candidates_v1" in session:
        print(f"OK: document_candidates_v1 FOUND ({len(session['document_candidates_v1'].get('candidates', []))} items).")
    else:
        print("MISSING: document_candidates_v1 NOT FOUND.")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
