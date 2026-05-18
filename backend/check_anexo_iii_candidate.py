import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory

async def check():
    session_id = "unaq-2026_paneles_solares"
    m = await get_connected_memory()
    session = await m.get_session(session_id)
    candidates = session.get("document_candidates_v1", {}).get("candidate_document_list", [])
    
    matches = [c for c in candidates if "Anexo III" in c.get("nombre", "")]
    
    print(f"Total matches for 'Anexo III' in candidates: {len(matches)}")
    for m_item in matches:
        print(f" - Name: {m_item.get('nombre')}")
        print(f"   Category: {m_item.get('categoria')}")
        print(f"   Action: {m_item.get('tipo_accion_final')}")

    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
