import asyncio
from app.memory.factory import MemoryAdapterFactory

async def force_nuke():
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    
    print("--- Force Nuking Sessions ---")
    sessions = await m.list_sessions()
    print(f"Found {len(sessions)} sessions to delete.")
    for s in sessions:
        sid = s['id']
        print(f"Deleting session {sid}...")
        success = await m.delete_session(sid)
        print(f"Result: {success}")
        
    print("\n--- Force Nuking Companies ---")
    companies = await m.get_companies()
    print(f"Found {len(companies)} companies to delete.")
    for c in companies:
        cid = c['id']
        print(f"Deleting company {cid}...")
        success = await m.delete_company(cid)
        print(f"Result: {success}")

    await m.disconnect()
    print("\nForce nuke complete.")

if __name__ == "__main__":
    asyncio.run(force_nuke())
