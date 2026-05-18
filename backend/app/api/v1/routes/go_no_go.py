"""
go_no_go.py — Endpoint de autorización del Semáforo Go/No-Go.

Permite al usuario autorizar brechas críticas y reanudar el pipeline,
o detenerlo para revisión. Cumple ISO/IEC 27034: datos sensibles fuera
de logs, ip_hash en auditoría, sanitización de respuesta HTTP.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from app.agents.mcp_context import MCPContextManager
from app.api.deps import get_connected_memory
from app.core.logging_config import get_logger
from app.services.job_service import update_job_status

logger = get_logger(__name__)
router = APIRouter()


def _clear_evidence_conflict_pending_questions(session_state: dict) -> dict:
    """Limpia pending_questions de conflictos de evidencia ya no accionables.

    Al autorizar Go/No-Go, estos conflictos pueden quedar "pegados" en la sesión
    y confundir al usuario durante la generación documental.
    """
    pending = list(session_state.get("pending_questions") or [])
    kept = [q for q in pending if str((q or {}).get("type") or "") != "evidence_profile_conflict"]
    if len(kept) == len(pending):
        return session_state

    session_state["pending_questions"] = kept
    if kept:
        idx_raw: Any = session_state.get("current_question_index", 0)
        try:
            idx = int(idx_raw)
        except (TypeError, ValueError):
            idx = 0
        session_state["current_question_index"] = max(0, min(idx, len(kept) - 1))
    else:
        session_state["current_question_index"] = 0
    return session_state


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AuthorizeRequest(BaseModel):
    """Cuerpo de la solicitud de autorización Go/No-Go."""

    user_override: bool
    brechas_autorizadas: List[str]
    company_id: Optional[str] = None
    company_data: dict = {}
    resume_generation: bool = True
    recalculate_only: bool = False  # Si True, solo recalcula el semáforo sin reanudar el pipeline


class AuthorizeResponse(BaseModel):
    """Respuesta estándar del endpoint de autorización."""

    success: bool
    data: dict
    message: str


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/{session_id}/authorize", response_model=AuthorizeResponse)
async def authorize_go_no_go(
    session_id: str,
    body: AuthorizeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> AuthorizeResponse:
    """Autoriza o detiene el pipeline en estado GO_NO_GO_PENDING.

    Args:
        session_id: ID de la sesión en pausa.
        body: Decisión del usuario con lista de brechas autorizadas.
        request: Request de FastAPI para extraer IP del cliente.
        background_tasks: Tareas de fondo para reanudar el pipeline.

    Returns:
        AuthorizeResponse con success, data y message.
    """
    memory = await get_connected_memory()
    try:
        session_state = await memory.get_session(session_id)
        if not session_state:
            return AuthorizeResponse(
                success=False, data={}, message="Sesión no encontrada."
            )

        decision = session_state.get("last_orchestrator_decision") or {}
        stop_reason = decision.get("stop_reason", "")

        # Recálculo rápido del semáforo sin reanudar el pipeline
        if body.recalculate_only:
            try:
                from app.agents.go_no_go import GoNoGoAgent
                from app.agents.mcp_context import MCPContextManager
                from app.contracts.agent_contracts import AgentInput
                from app.services.go_no_go_session_bridges import (
                    merge_company_data_with_session_evidence,
                )

                mcp = MCPContextManager(memory_repository=memory)
                merged_company = await merge_company_data_with_session_evidence(
                    memory,
                    session_id,
                    body.company_data or {},
                    persist_evidence_snap=True,
                )
                agent_input = AgentInput(
                    session_id=session_id,
                    company_id=body.company_id,
                    company_data=merged_company,
                )
                gng_res = await GoNoGoAgent(mcp).process(agent_input)
                gng_data = gng_res.data if hasattr(gng_res, "data") else {}
                # Persistir solo go_no_go_result — no sobreescribir tasks_completed
                fresh = await memory.get_session(session_id) or {}
                fresh["go_no_go_result"] = gng_data
                await memory.save_session(session_id, fresh)
                return AuthorizeResponse(
                    success=True,
                    data={"go_no_go_result": gng_data},
                    message="Semáforo recalculado.",
                )
            except Exception as exc:
                logger.error("go_no_go_recalculate_error", session_id=session_id, error=str(exc))
                return AuthorizeResponse(success=False, data={}, message=f"Error al recalcular: {exc}")

        if stop_reason != "GO_NO_GO_PENDING":
            return AuthorizeResponse(
                success=False,
                data={},
                message=f"El pipeline no está en estado GO_NO_GO_PENDING (estado actual: {stop_reason}).",
            )

        if not session_state.get("go_no_go_result"):
            return AuthorizeResponse(
                success=False,
                data={},
                message="No hay resultado Go/No-Go para esta sesión.",
            )

        # Auditoría ISO/IEC 27034: hash de IP, nunca la IP directa
        client_ip = request.client.host if request.client else "unknown"
        ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()

        if not body.user_override:
            # Usuario decide detener
            _log_audit_event(
                session_id=session_id,
                event_type="go_no_go_stopped",
                actor="user",
                details={"brechas_count": len(body.brechas_autorizadas)},
            )
            return AuthorizeResponse(
                success=True,
                data={},
                message="Pipeline detenido. Puedes revisar las brechas y volver a intentarlo.",
            )

        # Usuario autoriza continuar
        override_record = {
            "authorized_by": "user",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "brechas_autorizadas": body.brechas_autorizadas,
            "ip_hash": ip_hash,
        }
        # Persistir solo go_no_go_override — no sobreescribir tasks_completed
        fresh = await memory.get_session(session_id) or {}
        fresh["go_no_go_override"] = override_record
        fresh = _clear_evidence_conflict_pending_questions(fresh)
        await memory.save_session(session_id, fresh)

        _log_audit_event(
            session_id=session_id,
            event_type="go_no_go_authorized",
            actor="user",
            details={
                "brechas_autorizadas_count": len(body.brechas_autorizadas),
                "ip_hash": ip_hash,
            },
        )

        # Encolar reanudación del pipeline
        job_id = str(uuid.uuid4())
        update_job_status(
            job_id=job_id,
            status="QUEUED",
            progress={"stage": "go_no_go_resume", "pct": 0, "message": "Reanudando pipeline tras autorización Go/No-Go"},
        )

        from app.api.schemas.requests import ProcessBasesRequest
        resume_request = ProcessBasesRequest(
            session_id=session_id,
            company_id=body.company_id,
            company_data={**body.company_data, "mode": "generation_only"},
            resume_generation=True,
        )

        from app.api.v1.routes.agents import _run_orchestrator_job
        background_tasks.add_task(_run_orchestrator_job, job_id, resume_request)

        return AuthorizeResponse(
            success=True,
            data={"job_id": job_id, "session_id": session_id},
            message="Autorización registrada. Pipeline reanudado.",
        )

    except Exception as exc:
        logger.error(
            "go_no_go_authorize_error",
            session_id=session_id,
            error=str(exc),
        )
        return AuthorizeResponse(
            success=False, data={}, message=f"Error interno: {exc}"
        )
    finally:
        await memory.disconnect()


# ---------------------------------------------------------------------------
# Helper de auditoría
# ---------------------------------------------------------------------------

def _log_audit_event(
    session_id: str,
    event_type: str,
    actor: str,
    details: dict,
) -> None:
    """Registra un evento de auditoría estructurado sin datos sensibles.

    Args:
        session_id: ID de la sesión afectada.
        event_type: Tipo de evento (go_no_go_authorized, go_no_go_stopped).
        actor: Identificador del actor (user, system).
        details: Detalles del evento sin datos sensibles del perfil maestro.
    """
    logger.info(
        "audit_event",
        event_type=event_type,
        session_id=session_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        actor=actor,
        details=details,
    )
