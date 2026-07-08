import asyncio
from app.memory.factory import MemoryAdapterFactory

async def check():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    sess = await m.list_sessions()
    print(f"Sessions in DB: {len(sess)}")
    for s in sess:
        print(f" - ID: {s.get('id')} | Name: {s.get('name')}")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check())
