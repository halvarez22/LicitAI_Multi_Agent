import asyncio
import sys
import json

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory

async def list_sessions():
    m = await get_connected_memory()
    if not m:
        print("No DB connection")
        return
    
    sessions = await m.list_sessions()
    print(json.dumps(sessions, indent=2))
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(list_sessions())
