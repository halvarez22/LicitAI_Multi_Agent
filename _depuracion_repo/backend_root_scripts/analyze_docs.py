import asyncio
import sys
import os
import json

# Add the backend to sys.path to import settings
sys.path.append(os.getcwd())

from app.memory.factory import MemoryAdapterFactory

async def analyze():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    session_id = "suministro_e_instalacin_de_paneles_solares"
    session_data = await m.get_session(session_id)
    if not session_data:
        print("Session not found")
        return
    
    # Try to find candidates in different places
    candidates_raw = session_data.get("document_candidates_final") or session_data.get("document_candidates_v1")
    
    if isinstance(candidates_raw, dict):
        doc_list = candidates_raw.get("candidate_document_list") or []
    elif isinstance(candidates_raw, list):
        doc_list = candidates_raw
    else:
        doc_list = []

    summary = {}
    by_category = {}
    
    for c in doc_list:
        if not isinstance(c, dict):
            continue
        action = c.get("tipo_accion_final", "informativo")
        cat = c.get("categoria", "otros")
        
        if action not in summary:
            summary[action] = []
        summary[action].append(c)
        
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(c)

    print(f"Total Documents Detected: {len(doc_list)}")
    
    if "candidate_summary" in candidates_raw if isinstance(candidates_raw, dict) else {}:
        print(f"Summary from Data: {candidates_raw['candidate_summary']}")

    print("\nBreakdown by Action:")
    for action in sorted(summary.keys()):
        items = summary[action]
        print(f" - {action}: {len(items)}")
        # Show first 5 names
        names = [str(i.get('nombre')) for i in items[:5]]
        print(f"   Examples: {', '.join(names)}")

    print("\nBreakdown by Category:")
    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        print(f" - {cat}: {len(items)}")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(analyze())
