"""
observability.py — Fase 0 Hardening
Logs estructurados con correlation_id para trazabilidad del pipeline LicitAI.

Uso:
    from app.core.observability import get_logger, agent_span

    log = get_logger(__name__)
    log.info("agent_start", agent_id="analyst_001", session_id="...", correlation_id="...")

    async with agent_span(log, "analyst_001", session_id, correlation_id):
        result = await agent.process(...)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import structlog

# ─── Configurar structlog una sola vez ───────────────────────────────────────

def configure_structlog() -> None:
    """
    Configura structlog para emitir JSON estructurado.
    Llamar una vez en main.py / app startup.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),  # Cambiar a JSONRenderer en producción
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Obtiene un logger estructurado para un módulo."""
    return structlog.get_logger(name)


def generate_correlation_id() -> str:
    """Genera un correlation_id único para una ejecución de pipeline."""
    return str(uuid.uuid4())[:12]


# ─── Context manager para spans de agente ───────────────────────────────────

@asynccontextmanager
async def agent_span(
    log: structlog.stdlib.BoundLogger,
    agent_id: str,
    session_id: str,
    correlation_id: str,
) -> AsyncIterator[None]:
    """
    Context manager que loggea inicio/fin de agente con duración.

    Uso:
        async with agent_span(log, "analyst_001", session_id, correlation_id):
            result = await agent.process(...)
    """
    start = time.monotonic()
    log.info(
        "agent_start",
        agent_id=agent_id,
        session_id=session_id,
        correlation_id=correlation_id,
    )
    try:
        yield
        duration = time.monotonic() - start
        log.info(
            "agent_end",
            agent_id=agent_id,
            session_id=session_id,
            correlation_id=correlation_id,
            duration_sec=round(duration, 3),
            outcome="success",
        )
    except Exception as exc:
        duration = time.monotonic() - start
        log.error(
            "agent_end",
            agent_id=agent_id,
            session_id=session_id,
            correlation_id=correlation_id,
            duration_sec=round(duration, 3),
            outcome="error",
            error=str(exc)[:500],
        )
        raise


def log_contract_violation(
    log: structlog.stdlib.BoundLogger,
    agent_id: str,
    session_id: str,
    correlation_id: str,
    field: str,
    detail: str,
) -> None:
    """Log estructurado para violaciones de contrato de datos."""
    log.error(
        "contract_violation",
        agent_id=agent_id,
        session_id=session_id,
        correlation_id=correlation_id,
        field=field,
        detail=detail,
    )


def log_state_migration(
    log: structlog.stdlib.BoundLogger,
    session_id: str,
    from_version: Optional[int],
    to_version: int,
) -> None:
    """Log estructurado para migraciones de estado de sesión."""
    log.info(
        "session_state_migrated",
        session_id=session_id,
        from_version=from_version,
        to_version=to_version,
    )


def log_circuit_breaker_event(
    log: structlog.stdlib.BoundLogger,
    event: str,  # "opened" | "closed" | "half_open"
    correlation_id: str,
    failure_count: int = 0,
) -> None:
    """Log estructurado para eventos del circuit breaker."""
    log.warning(
        "circuit_breaker_event",
        event=event,
        correlation_id=correlation_id,
        failure_count=failure_count,
    )


def log_llm_retry(
    log: structlog.stdlib.BoundLogger,
    attempt: int,
    max_attempts: int,
    delay_sec: float,
    correlation_id: str,
    error: str = "",
) -> None:
    """Log estructurado para reintentos de LLM."""
    log.warning(
        "llm_retry",
        attempt=attempt,
        max_attempts=max_attempts,
        delay_sec=delay_sec,
        correlation_id=correlation_id,
        error=error[:200] if error else "",
    )
