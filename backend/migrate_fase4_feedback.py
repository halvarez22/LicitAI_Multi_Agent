import asyncio
from sqlalchemy import text
from app.memory.factory import MemoryAdapterFactory
from app.models.feedback import ExtractionFeedback

async def migrate():
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    # Usar el motor de SQLAlchemy para ejecutar SQL plano
    async with memory.engine.begin() as conn:
        print("[*] Iniciando creación de tabla 'extraction_feedback'...")
        
        # Crear la tabla si no existe usando run_sync y Base.metadata
        from app.models.base import Base
        await conn.run_sync(Base.metadata.create_all)
        
        print("[+] Migración de Fase 4 completada exitosamente.")

    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(migrate())
