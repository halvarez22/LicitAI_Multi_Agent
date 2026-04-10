from typing import Optional
import os

from app.config.settings import settings
from app.memory.repository import MemoryRepository
from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter


class MemoryAdapterFactory:
    """Factory para crear el adaptador de memoria según configuración del entorno."""

    _instance: Optional[MemoryRepository] = None

    @classmethod
    def reset_instance(cls) -> None:
        """Limpia el singleton (p. ej. tras fallo de conexión para permitir reintento)."""
        cls._instance = None

    @classmethod
    def create_adapter(cls) -> Optional[MemoryRepository]:
        if cls._instance is None:
            backend = (settings.MEMORY_BACKEND or os.getenv("MEMORY_BACKEND", "postgres")).lower()
            if backend == "postgres":
                db_url = settings.DATABASE_URL or os.getenv("DATABASE_URL")
                cls._instance = PostgresMemoryAdapter(
                    connection_string=db_url,
                    encryption_key=os.getenv("MEMORY_ENCRYPTION_KEY"),
                )
            elif backend == "sqlite":
                raise NotImplementedError("SQLite fallback no implementado en esta vista.")
            else:
                raise ValueError(f"Backend de memoria no soportado: {backend}")

        return cls._instance
