"""
Contexto de memoria por hilo/event loop.

Durante jobs aislados (thread + loop propio) el singleton global de Postgres
pertenece al loop de Uvicorn. El override evita "Future attached to a different loop".
"""
from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.memory.repository import MemoryRepository

_memory_override: ContextVar[Optional["MemoryRepository"]] = ContextVar(
    "licitai_memory_override",
    default=None,
)


def set_memory_override(adapter: Optional["MemoryRepository"]) -> Token:
    """Fija el adaptador activo para el hilo/contexto async actual."""
    return _memory_override.set(adapter)


def reset_memory_override(token: Token) -> None:
    """Restaura el override previo (normalmente None en el hilo del API)."""
    _memory_override.reset(token)


def get_memory_override() -> Optional["MemoryRepository"]:
    return _memory_override.get()
