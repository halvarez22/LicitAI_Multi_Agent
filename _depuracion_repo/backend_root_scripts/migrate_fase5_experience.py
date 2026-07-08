import asyncio
import os
import sys

# Añadir el directorio actual al path para importar app
sys.path.append(os.getcwd())

from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
from app.models.base import Base
from sqlalchemy import create_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    """Crea las tablas para la Fase 5: Experiencia y Outcomes."""
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/licitaciones")
    
    # El PostgresMemoryAdapter ya maneja la creación de tablas por defecto al conectar
    # pero vamos a forzarlo explícitamente para asegurar que LicitacionOutcome exista.
    adapter = PostgresMemoryAdapter(database_url)
    
    try:
        logger.info("Iniciando migración Fase 5 (Outcomes)...")
        # Usamos el motor síncrono para Base.metadata.create_all si es necesario, 
        # o confiamos en el arranque del adaptador.
        sync_url = database_url.replace("+asyncpg", "")
        from sqlalchemy import create_engine
        engine = create_engine(sync_url)
        
        # Importamos los modelos para asegurar que están registrados en Base.metadata
        from app.models.outcome import LicitacionOutcome
        
        Base.metadata.create_all(engine)
        logger.info("Tablas de Fase 5 creadas exitosamente.")
        
    except Exception as e:
        logger.error(f"Error en migración Fase 5: {e}")
    finally:
        pass

if __name__ == "__main__":
    asyncio.run(migrate())
