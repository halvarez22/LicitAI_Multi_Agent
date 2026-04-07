import asyncio
from app.memory.factory import MemoryAdapterFactory

async def list_sess():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    sess = await m.get_sessions()
    print(f"Total Sessions: {len(sess)}")
    for s in sess:
        print(f" - ID: {s.get('id')} | Status: {s.get('content', {}).get('status')}")
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(list_sess())
