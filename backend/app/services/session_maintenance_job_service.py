"""
Jobs async de mantenimiento de sesión (rehidratación) sin bloquear el worker HTTP.

Patrón alineado a ``agents._run_orchestrator_job_isolated``: thread + event loop propio.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

from app.core.logging_config import get_logger
from app.services.job_service import (
    clear_session_maintenance_job,
    get_job_status,
    link_session_maintenance_job,
    update_job_status,
)

logger = get_logger(__name__)


def create_rehydrate_job(session_id: str) -> str:
    """Reserva job_id en Redis (QUEUED) y lo vincula a la sesión."""
    job_id = str(uuid.uuid4())
    update_job_status(
        job_id,
        "QUEUED",
        {
            "stage": "rehydrate",
            "pct": 0,
            "message": "Encolando rehidratación de artefactos",
            "job_type": "session_rehydrate",
            "session_id": session_id,
        },
    )
    link_session_maintenance_job(session_id, job_id)
    return job_id


async def run_rehydrate_job_in_thread(
    job_id: str,
    session_id: str,
    *,
    company_id: Optional[str] = None,
    force_junta: bool = False,
) -> None:
    """Ejecuta rehydrate en thread dedicado (no monopoliza loop Uvicorn)."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        _thread_main_rehydrate,
        job_id,
        session_id,
        company_id,
        force_junta,
    )


def _thread_main_rehydrate(
    job_id: str,
    session_id: str,
    company_id: Optional[str],
    force_junta: bool,
) -> None:
    from app.config.settings import settings
    from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter
    from app.memory.runtime import reset_memory_override, set_memory_override

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    adapter = PostgresMemoryAdapter(
        connection_string=settings.DATABASE_URL or os.getenv("DATABASE_URL"),
        encryption_key=os.getenv("MEMORY_ENCRYPTION_KEY"),
    )

    async def _run() -> None:
        token = set_memory_override(adapter)
        try:
            await adapter.connect()
            update_job_status(
                job_id,
                "RUNNING",
                {
                    "stage": "rehydrate",
                    "pct": 15,
                    "message": "Reconstruyendo candidatos, hitos y junta…",
                    "job_type": "session_rehydrate",
                },
            )
            from app.services.analysis_artifacts_rehydrate_service import (
                rehydrate_after_analysis_pipeline,
            )
            from app.services.session_health_service import assess_session_health

            result = await rehydrate_after_analysis_pipeline(
                adapter,
                session_id,
                company_id=company_id,
                commit_snapshot=True,
                force_junta_refresh=force_junta,
            )
            fresh = await adapter.get_session(session_id) or {}
            health = assess_session_health(session_id, fresh)
            payload = {
                "rehydrate": result.to_dict(),
                "session_health": health,
            }
            if result.success:
                update_job_status(
                    job_id,
                    "COMPLETED",
                    {
                        "stage": "rehydrate",
                        "pct": 100,
                        "message": "Artefactos actualizados",
                    },
                    result={
                        "status": "success",
                        "session_id": session_id,
                        "data": payload,
                    },
                )
            else:
                update_job_status(
                    job_id,
                    "FAILED",
                    {"stage": "rehydrate", "pct": 100},
                    error=result.error or "Rehidratación incompleta",
                    result={
                        "status": "partial",
                        "session_id": session_id,
                        "data": payload,
                    },
                )
        except Exception as exc:
            logger.exception("rehydrate_job_failed session=%s job=%s", session_id, job_id)
            update_job_status(
                job_id,
                "FAILED",
                {"stage": "rehydrate", "pct": 100},
                error=str(exc)[:500],
                forensic_traceback={"reason": "rehydrate_exception", "session_id": session_id},
            )
        finally:
            reset_memory_override(token)
            await adapter.disconnect()
            clear_session_maintenance_job(session_id)

    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def get_rehydrate_job_result(job_id: str) -> Optional[Dict[str, Any]]:
    """Extrae payload de resultado si el job terminó."""
    job = get_job_status(job_id)
    if not job:
        return None
    result = job.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return None
    return None
