"""
Dependencias compartidas de la API (memoria / PostgreSQL).
"""
from fastapi import HTTPException

from app.memory.factory import MemoryAdapterFactory

_DB_UNAVAILABLE_MSG = (
    "PostgreSQL no disponible. Si corres el API en el host sin Docker, define DATABASE_URL "
    "con host 127.0.0.1 (el nombre 'database' solo resuelve dentro de docker-compose). "
    "Ejemplo: postgresql://postgres:postgres@127.0.0.1:5432/licitaciones. "
    "Alternativa: docker compose up -d"
)


async def get_connected_memory():
    """
    Devuelve el adaptador de memoria con sesión SQLAlchemy lista.
    Antes de usar ``async_session()``, valida conexión para evitar errores opacos.
    """
    memory = MemoryAdapterFactory.create_adapter()
    if memory is None:
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE_MSG)
    connected = await memory.connect()
    if not connected or getattr(memory, "async_session", None) is None:
        raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE_MSG)
    return memory
