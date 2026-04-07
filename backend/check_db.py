import asyncio
import os
import sys

# Add the current directory to sys.path to find 'app'
sys.path.append(os.getcwd())

from app.memory.factory import MemoryAdapterFactory

async def main():
    try:
        conn_str = "postgresql://postgres:postgres@localhost:5432/licitaciones"
        from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
        memory = PostgresMemoryAdapter(connection_string=conn_str)
        connected = await memory.connect()
        if not connected:
            print("Could not connect to database")
            return
        
        sessions = await memory.list_sessions()
        for s in sessions:
            print(f"ID: {s['id']} | Name: {s.get('name')} | Updated: {s.get('updated_at')}")
        
        companies = await memory.get_companies()
        print("\n--- Companies ---")
        for c in companies:
            print(f"ID: {c['id']} | Name: {c['name']}")
            
        await memory.disconnect()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
