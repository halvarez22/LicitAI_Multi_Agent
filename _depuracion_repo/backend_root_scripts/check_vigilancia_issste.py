import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check_session_docs():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    session_id = "suministro_e_instalacin_de_paneles_solares"
    docs = await m.get_documents(session_id)
    print(f"Total Documents for {session_id}: {len(docs)}")
    for d in docs:
        print(f" - Filename: {d.get('metadata', {}).get('filename')}")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check_session_docs())
