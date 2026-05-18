import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory
from app.services.document_candidate_list_service import build_candidate_document_list

async def repair():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    session = await m.get_session(session_id)
    
    # Re-calculate with the NEW filter
    compliance = {}
    tasks = session.get("tasks_completed", [])
    for t in reversed(tasks):
        if t.get("task") == "stage_completed:compliance":
            compliance = t.get("result", {})
            break
    
    comp_data = compliance.get("data", {})
    
    print(f"Re-calculating candidates for {session_id} with the new 'Refinement' filter...")
    new_candidates = build_candidate_document_list(
        compliance_master_list=comp_data
    )
    
    dictamen = session.get("dictamen")
    if dictamen:
        dictamen["fastTrackDocumentCandidates"] = new_candidates
        session["dictamen"] = dictamen
        session["document_candidates_v1"] = new_candidates
        session["document_candidates_final"] = new_candidates
        
        await m.save_session(session_id, session)
        print(f"DONE! List reduced to {len(new_candidates.get('candidate_document_list', []))} deliverables.")
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(repair())
