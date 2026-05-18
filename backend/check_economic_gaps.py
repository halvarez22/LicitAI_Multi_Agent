import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check_pending():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    
    session_id = "vigilancia_issste"
    state = await m.get_session(session_id)
    if not state:
        print(f"No se pudo recuperar el estado para {session_id}")
        return

    pending = state.get("pending_questions", [])
    print(f"--- PREGUNTAS PENDIENTES ({len(pending)}) ---")
    for i, q in enumerate(pending):
        print(f"{i+1}. [{q.get('type')}] {q.get('label')}")

if __name__ == "__main__":
    asyncio.run(check_pending())
