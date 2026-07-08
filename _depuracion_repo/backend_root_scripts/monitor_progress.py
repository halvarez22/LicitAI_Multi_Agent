import asyncio
import redis
from app.memory.factory import MemoryAdapterFactory
from app.config.settings import settings

async def check_status():
    print("--- Checking Postgres Companies ---")
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    comps = await m.get_companies()
    print(f"Total Companies: {len(comps)}")
    for c in comps:
        print(f" - {c['name']} (ID: {c['id']})")
    await m.disconnect()

    print("\n--- Checking Redis Jobs ---")
    try:
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, decode_responses=True)
        keys = r.keys("job:*")
        print(f"Total Active Jobs: {len(keys)}")
        for key in keys:
            data = r.get(key)
            print(f" - Key: {key} | Data: {data[:200]}...")
    except Exception as e:
        print(f"Redis Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_status())
