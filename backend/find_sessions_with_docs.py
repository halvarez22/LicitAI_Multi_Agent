import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def find_sessions_with_docs():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    sessions = await m.list_sessions()
    for s in sessions:
        session_id = s.get("id")
        data = await m.get_session(session_id)
        if data:
            c = data.get("document_candidates_final") or data.get("document_candidates_v1")
            if c:
                if isinstance(c, dict):
                    doc_list = c.get("candidate_document_list") or []
                elif isinstance(c, list):
                    doc_list = c
                else:
                    doc_list = []
                print(f"Session {session_id} has {len(doc_list)} documents.")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(find_sessions_with_docs())
