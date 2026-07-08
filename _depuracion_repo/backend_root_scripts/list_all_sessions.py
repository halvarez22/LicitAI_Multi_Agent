import asyncio
from app.memory.factory import MemoryAdapterFactory

async def list_sessions():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    sessions = await m.list_sessions()
    print("--- LISTADO DE SESIONES ---")
    for s in sessions:
        if isinstance(s, dict):
            print(f"ID: {s.get('id')} | NOMBRE: {s.get('name')}")
        else:
            print(f"ID: {s}")

if __name__ == "__main__":
    asyncio.run(list_sessions())
