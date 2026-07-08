import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def get_session_dictamen():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    session_id = "prueba_e2e_desde_la_ui_1"
    session_data = await m.get_session(session_id)
    if session_data:
        candidates_raw = session_data.get("document_candidates_final") or session_data.get("document_candidates_v1")
        if isinstance(candidates_raw, dict):
            doc_list = candidates_raw.get("candidate_document_list") or []
        elif isinstance(candidates_raw, list):
            doc_list = candidates_raw
        else:
            doc_list = []
        
        print(f"Total Documents for {session_id}: {len(doc_list)}")
        if doc_list:
            # Show summary
            summary = {}
            for d in doc_list:
                action = d.get("tipo_accion_final", "informativo")
                summary[action] = summary.get(action, 0) + 1
            print(f"Summary: {summary}")
            # Show first 5
            for d in doc_list[:5]:
                print(f" - {d.get('nombre')} ({d.get('tipo_accion_final')})")
    else:
        print("Session not found")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(get_session_dictamen())
