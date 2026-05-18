import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check_names():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    ids = ["vigilancia_issste", "suministro_e_instalacin_de_paneles_solares"]
    for sid in ids:
        s = await m.get_session(sid)
        print(f"ID: {sid} | Name: {s.get('name') if s else 'N/A'}")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check_names())
