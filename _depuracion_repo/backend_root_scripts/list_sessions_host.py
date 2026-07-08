import asyncio
import os
import sys
from sqlalchemy import create_sqlalchemy_engine, text # assuming standard libs or installed

# Set env vars for host access
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/licitaciones"

async def list_sessions():
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/licitaciones")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT id FROM sessions LIMIT 10"))
        for row in result:
            print(f"Session ID: {row[0]}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(list_sessions())
