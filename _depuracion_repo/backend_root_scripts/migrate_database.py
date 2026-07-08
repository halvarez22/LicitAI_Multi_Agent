import asyncio
from sqlalchemy import text
from app.memory.factory import MemoryAdapterFactory

async def migrate():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    # Usar el motor de SQLAlchemy para ejecutar SQL plano
    async with memory.engine.begin() as conn:
        print("[*] Iniciando migración profunda de la tabla 'companies'...")
        
        # 1. Agregar columna 'rfc' si no existe
        await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS rfc VARCHAR"))
        
        # 2. Agregar columna 'catalog' si no existe
        await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS catalog JSONB DEFAULT '[]'"))
        
        # 3. Asegurar columna 'docs'
        await conn.execute(text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS docs JSONB DEFAULT '{}'"))
        
        print("[+] Migración completada exitosamente.")

    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(migrate())
