import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory

async def repair():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    session = await m.get_session(session_id)
    
    dictamen = session.get("dictamen")
    candidates = session.get("document_candidates_v1")
    
    if not dictamen:
        print("No dictamen found to repair.")
        return
        
    if not candidates:
        print("No candidates found in session to inject.")
        return
        
    print(f"Repairing dictamen for {session_id}...")
    dictamen["fastTrackDocumentCandidates"] = candidates
    session["dictamen"] = dictamen
    
    await m.save_session(session_id, session)
    print("Dictamen updated with fastTrackDocumentCandidates.")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(repair())
