from typing import Optional
from app.memory.repository import MemoryRepository
from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
import os

class MemoryAdapterFactory:
    """Factory para crear el adaptador de memoria según configuración del entorno."""
    
    _instance: Optional[MemoryRepository] = None

    @classmethod
    def create_adapter(cls) -> Optional[MemoryRepository]:
        if cls._instance is None:
            backend = os.getenv('MEMORY_BACKEND', 'postgres').lower()
            
            if backend == 'postgres':
                db_url = os.getenv('DATABASE_URL')
                cls._instance = PostgresMemoryAdapter(
                    connection_string=db_url,
                    encryption_key=os.getenv('MEMORY_ENCRYPTION_KEY')
                )
            elif backend == 'sqlite':
                raise NotImplementedError("SQLite fallback no implementado en esta vista.")
            else:
                raise ValueError(f"Backend de memoria no soportado: {backend}")
        
        return cls._instance
