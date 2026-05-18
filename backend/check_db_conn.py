from sqlalchemy.ext.asyncio import create_async_engine
import asyncio

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/licitaciones"

async def check():
    print(f"Checking {DATABASE_URL}")
    try:
        engine = create_async_engine(DATABASE_URL)
        async with engine.connect() as conn:
            print("Successfully connected to the database!")
            from sqlalchemy import text
            res = await conn.execute(text("SELECT 1"))
            print(f"Query result: {res.scalar()}")
        await engine.dispose()
    except Exception as e:
        print(f"Error connecting to database: {e}")

if __name__ == "__main__":
    asyncio.run(check())
