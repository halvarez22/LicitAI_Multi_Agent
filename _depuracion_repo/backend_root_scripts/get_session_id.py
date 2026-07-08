import asyncio
import sys

# Add parent dir to path to import app modules
sys.path.append(".")

from app.api.deps import get_connected_memory

async def find():
    m = await get_connected_memory()
    if not m:
        print("No DB connection")
        return
    
    sessions = await m.list_sessions()
    target = [s for s in sessions if "PANELES SOLARES" in s.get("name", "").upper() or "UNAQ-2026" in s["id"].upper()]
    
    for s in target:
        print(f"ID: {s['id']} | Name: {s['name']}")
    
    await m.disconnect()

if __name__ == "__main__":
    asyncio.run(find())
