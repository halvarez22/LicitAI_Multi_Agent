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
    
    dictamen = session.get("dictamen")
    print(f"--- DICTAMEN KEYS FOR {session_id} ---")
    if dictamen:
        print(f"Keys: {list(dictamen.keys())}")
        ft = dictamen.get("fastTrackDocumentCandidates")
        if ft:
            print(f"OK: fastTrackDocumentCandidates type: {type(ft)}")
            if isinstance(ft, dict):
                print(f"Content: {json.dumps(ft, indent=2)}")
            else:
                print(f"Content: {ft}")
        else:
            print("MISSING: fastTrackDocumentCandidates NOT FOUND in dictamen.")
            # Check other possible names
            for k in dictamen.keys():
                if "candidate" in k.lower() or "document" in k.lower():
                    print(f"   Found related key: {k}")

        causales = dictamen.get("causales") or []
        print(f"Causales: {len(causales)} items.")
        cats = {}
        for c in causales:
            cat = c.get("categoria_llm") or "none"
            cats[cat] = cats.get(cat, 0) + 1
        print(f"Categories count: {cats}")
    else:
        print("MISSING: Dictamen not found in session.")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
