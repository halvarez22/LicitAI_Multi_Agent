import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def check_candidates():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    session_id = "suministro_e_instalacin_de_paneles_solares"
    s = await m.get_session(session_id)
    if s:
        c = s.get("document_candidates_final") or s.get("document_candidates_v1")
        if isinstance(c, dict):
            doc_list = c.get("candidate_document_list") or []
            print(f"Total: {len(doc_list)}")
            for d in doc_list[:20]:
                print(f" - {d.get('nombre')} | Category: {d.get('categoria')} | Snippet: {d.get('evidence_snippet')[:50]}...")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check_candidates())
