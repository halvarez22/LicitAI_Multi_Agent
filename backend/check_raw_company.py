import asyncio
import json
from app.memory.factory import MemoryAdapterFactory

async def check_raw():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    cid = "co_1777426690421"
    c = await m.get_company(cid)
    print(json.dumps(c, indent=2))
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(check_raw())
