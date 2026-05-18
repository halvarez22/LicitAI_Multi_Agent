
import asyncio
import sys
sys.path.append("/app")
from app.memory.factory import MemoryAdapterFactory

async def dump():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    session = await memory.get_session("limpieza_isapeg")
    if not session:
        print("Sesión no encontrada")
        return
    
    pending = session.get("pending_questions") or []
    if pending:
        print("--- PRIMERA PREGUNTA PENDIENTE ---")
        print(pending[0].get("question"))
        
        blocking = pending[0].get("blocking_items") or []
        if blocking:
            print("--- INSTRUCCIÓN BLOQUEANTE ---")
            print(blocking[0].get("instruction"))

if __name__ == "__main__":
    asyncio.run(dump())
