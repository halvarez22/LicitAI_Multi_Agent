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
    
    candidates = session.get("candidate_document_list")
    
    print(f"--- DATA ANALYSIS FOR {session_id} ---")
    if candidates is None:
        print("MISSING: 'candidate_document_list' NOT FOUND in session object.")
    elif not isinstance(candidates, list):
        print(f"WARNING: 'candidate_document_list' exists but is type {type(candidates)}.")
    else:
        print(f"OK: Found {len(candidates)} candidate documents in DB.")
        for i, c in enumerate(candidates[:5]):
            # Use ascii representation to avoid encoding errors
            name = ascii(c.get('nombre'))
            cat = ascii(c.get('categoria'))
            print(f"   [{i}] {name} ({cat})")
    
    dictamen = session.get("dictamen")
    if dictamen:
        status = ascii(dictamen.get('status'))
        print(f"OK: Dictamen present (status: {status})")
        if "candidate_document_list" in dictamen:
            print(f"   WARNING: Candidates found INSIDE dictamen object ({len(dictamen['candidate_document_list'])} items).")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
