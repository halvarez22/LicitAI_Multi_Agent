import asyncio
import os
import sys
import json
import redis
import chromadb
from sqlalchemy import text

# Add backend to sys.path
sys.path.append(os.getcwd())

from app.memory.factory import MemoryAdapterFactory
from app.config.settings import settings
from app.services.vector_service import VectorDbServiceClient

async def nuke_postgres():
    print("--- Nuking Postgres ---")
    m = MemoryAdapterFactory.create_adapter()
    await m.connect()
    
    # We use raw SQL to truncate all tables and reset sequences
    async with m.async_session() as db_session:
        # Disable foreign key checks for truncation (Postgres way)
        tables = [
            "session_line_items",
            "extraction_feedback",
            "licitacion_outcomes",
            "agent_states",
            "documents",
            "sessions",
            "companies"
        ]
        
        for table in tables:
            try:
                print(f"Truncating {table}...")
                await db_session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
            except Exception as e:
                print(f"Error truncating {table}: {e}")
        
        await db_session.commit()
    
    await m.disconnect()
    print("Postgres nuke complete.")

def nuke_chroma():
    print("\n--- Nuking ChromaDB ---")
    try:
        # Use localhost directly as we are running outside docker
        client = chromadb.HttpClient(host="127.0.0.1", port=8000)
        # Get all collections
        collections = client.list_collections()
        print(f"Found {len(collections)} collections.")
        for col in collections:
            print(f"Deleting collection: {col.name}")
            client.delete_collection(col.name)
        print("ChromaDB nuke complete.")
    except Exception as e:
        print(f"Error nuking ChromaDB: {e}")

def nuke_redis():
    print("\n--- Nuking Redis ---")
    try:
        r = redis.Redis(
            host=settings.REDIS_HOST, 
            port=settings.REDIS_PORT, 
            decode_responses=True
        )
        keys = r.keys("job:*")
        print(f"Found {len(keys)} job keys.")
        for key in keys:
            r.delete(key)
        
        # Also clear any other app keys if needed
        # r.flushdb() # This might be too aggressive if shared, but usually safe for dev
        print("Redis keys deleted.")
        print("Redis nuke complete.")
    except Exception as e:
        print(f"Error nuking Redis: {e}")

async def main():
    print("STARTING TOTAL CLEANUP")
    await nuke_postgres()
    nuke_chroma()
    nuke_redis()
    print("\nSYSTEM IS NOW CLEAN AS A WHISTLE")

if __name__ == "__main__":
    asyncio.run(main())
