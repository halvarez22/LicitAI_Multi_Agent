import asyncio
import os
from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter

async def main():
    conn_str = "postgresql://postgres:postgres@localhost:5432/licitaciones"
    repo = PostgresMemoryAdapter(conn_str)
    await repo.connect()
    res = await repo.get_outcome("licitacin_pblica_nacional_presencial__40004001-003-24_")
    print(f"Outcome fingerprint: {res.get('fingerprint') if res else 'None'}")
    await repo.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
