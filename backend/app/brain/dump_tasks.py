
import asyncio
import sys
sys.path.append("/app")
from app.memory.factory import MemoryAdapterFactory

async def dump_tasks():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    session = await memory.get_session("limpieza_isapeg")
    
    tasks = session.get("tasks_completed") or []
    for t in tasks:
        if t.get("task") == "economic_proposal":
            print("--- RESULTADO ECONÓMICO ENCONTRADO ---")
            print(str(t.get("result", {}))[:1000])

if __name__ == "__main__":
    asyncio.run(dump_tasks())
