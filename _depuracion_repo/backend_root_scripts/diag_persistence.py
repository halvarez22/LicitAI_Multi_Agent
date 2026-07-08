import asyncio
import os
from app.memory.factory import MemoryAdapterFactory

async def check_session_docs():
    conn_str = "postgresql://postgres:postgres@localhost:5432/licitaciones"
    from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
    adapter = PostgresMemoryAdapter(connection_string=conn_str)
    await adapter.connect()
    
    sessions = await adapter.list_sessions()
    print(f"--- REPORTE DE SESIONES ({len(sessions)}) ---")
    
    for s in sessions[:10]: # Ver las últimas 10
        sid = s['id']
        docs = await adapter.get_documents(sid)
        if docs:
            print(f"Sesión: {sid} | Nombre: {s.get('name')} | Documentos: {len(docs)}")
            for d in docs:
                status = d['content'].get('status', 'N/A')
                print(f"  - Doc: {d['metadata'].get('filename')} | Status: {status}")
        
    await adapter.disconnect()

if __name__ == "__main__":
    asyncio.run(check_session_docs())
