import asyncio
import sys
import json

sys.path.append(".")
from app.api.deps import get_connected_memory

async def list_c():
    m = await get_connected_memory()
    companies = await m.get_companies()
    print(json.dumps(companies, indent=2))
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(list_c())
