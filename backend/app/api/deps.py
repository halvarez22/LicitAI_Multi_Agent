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
    last_error: Exception | None = None
    for attempt in range(2):
        memory = MemoryAdapterFactory.create_adapter()
        if memory is None:
            raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE_MSG)
        try:
            connected = await memory.connect()
            if not connected or getattr(memory, "async_session", None) is None:
                raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE_MSG)
            return memory
        except RuntimeError as exc:
            last_error = exc
            if attempt == 0 and "different loop" in str(exc).lower():
                engine = getattr(memory, "engine", None)
                if engine is not None:
                    try:
                        await engine.dispose()
                    except Exception:
                        pass
                MemoryAdapterFactory.reset_instance()
                continue
            raise
    if last_error is not None:
        raise last_error
    raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE_MSG)
