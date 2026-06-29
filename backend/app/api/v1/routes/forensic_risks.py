"""
Endpoint HITL para decisiones sobre riesgos forenses del dictamen.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import get_connected_memory
from app.core.logging_config import get_logger
from app.api.schemas.responses import GenericResponse
from app.services.forensic_risk_service import (
    apply_risk_decision_updates,
    attach_and_hydrate_forensic_risks,
    attach_forensic_risks_to_dictamen,
    can_continue_with_risks,
    merge_risk_decisions_into_items,
)

logger = get_logger(__name__)
router = APIRouter()


class RiskDecisionUpdate(BaseModel):
    risk_id: str
    status: Literal["accepted", "rejected", "pending"]
    user_note: Optional[str] = None


class RiskDecisionRequest(BaseModel):
    decisions: List[RiskDecisionUpdate] = Field(default_factory=list)
    batch_action: Optional[Literal["continue_assuming_risks", "stop_expediente"]] = None


@router.post("/{session_id}/decisions", response_model=GenericResponse)
async def post_forensic_risk_decisions(session_id: str, body: RiskDecisionRequest) -> GenericResponse:
    """Persiste decisiones del usuario sobre riesgos forenses (auditable)."""
    memory = await get_connected_memory()
    try:
        session_data = await memory.get_session(session_id) or {}
        if not session_data:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)

        dictamen = session_data.get("dictamen")
        if not isinstance(dictamen, dict):
            return GenericResponse(
                success=False,
                message="No hay dictamen en la sesión. Ejecuta primero el análisis de bases.",
                data=None,
            )

        dictamen = attach_forensic_risks_to_dictamen(dictamen)
        session_data["dictamen"] = dictamen
        forensic_risks = dictamen.get("forensic_risks_v1") or {}

        if body.batch_action == "continue_assuming_risks":
            if not can_continue_with_risks(forensic_risks, session_data.get("risk_decisions_v1")):
                return GenericResponse(
                    success=False,
                    message=(
                        "Hay causas de desechamiento (bloqueantes) sin decisión de aceptación. "
                        "Revísalas una por una antes de continuar."
                    ),
                    data=None,
                )

        updates = [d.model_dump() for d in body.decisions]
        record = apply_risk_decision_updates(
            session_data.get("risk_decisions_v1"),
            decision_updates=updates,
            batch_action=body.batch_action,
        )
        session_data["risk_decisions_v1"] = record

        if body.batch_action == "stop_expediente":
            decision = dict(session_data.get("last_orchestrator_decision") or {})
            decision["stop_reason"] = "FORENSIC_RISK_REVIEW_STOP"
            decision["user_message"] = (
                "Detuviste el expediente tras revisar riesgos forenses. "
                "Puedes corregir documentos o consultar al experto antes de continuar."
            )
            session_data["last_orchestrator_decision"] = decision

        await memory.save_session(session_id, session_data)

        merged = merge_risk_decisions_into_items(forensic_risks, record)
        logger.info(
            "forensic_risk_decisions_saved session=%s batch=%s updates=%s",
            session_id,
            body.batch_action,
            len(updates),
        )
        return GenericResponse(
            success=True,
            message="Decisiones de riesgo guardadas",
            data={
                "risk_decisions_v1": record,
                "forensic_risks_v1": merged,
                "can_continue": can_continue_with_risks(forensic_risks, record),
            },
        )
    except Exception as exc:
        logger.error("forensic_risk_decisions_failed session=%s err=%s", session_id, exc)
        return GenericResponse(success=False, message=f"Error al guardar decisiones: {exc}", data=None)


@router.post("/{session_id}/reindex-bases", response_model=GenericResponse)
async def reindex_session_bases(session_id: str, force: bool = True) -> GenericResponse:
    """Reindexa documentos ANALYZED de la sesión en Chroma (HRU, universal)."""
    memory = await get_connected_memory()
    try:
        from app.services.vector_sync_service import VectorSyncService

        result = await VectorSyncService().ensure_session_indexed(memory, session_id, force=force)
        return GenericResponse(
            success=True,
            message="Reindexación de bases completada",
            data=result,
        )
    except Exception as exc:
        logger.error("forensic_reindex_bases_failed session=%s err=%s", session_id, exc)
        return GenericResponse(success=False, message=str(exc), data=None)


@router.get("/{session_id}/evidence", response_model=GenericResponse)
async def get_forensic_risk_evidence(
    session_id: str,
    literal: str,
    risk_id: Optional[str] = None,
) -> GenericResponse:
    """Resuelve evidencia v1 para un literal de riesgo sin párrafo completo."""
    memory = await get_connected_memory()
    try:
        if not literal or not str(literal).strip():
            return GenericResponse(success=False, message="Parámetro literal requerido", data=None)
        session_data = await memory.get_session(session_id) or {}
        from app.services.forensic_risk_evidence_enrichment_service import hydrate_forensic_risk_item_evidence

        item = {"texto": str(literal).strip(), "risk_id": risk_id}
        enriched = await hydrate_forensic_risk_item_evidence(
            session_id,
            item,
            session_state=session_data,
            memory=memory,
        )
        return GenericResponse(success=True, message="Evidencia resuelta", data=enriched.get("evidence_v1"))
    except Exception as exc:
        logger.error("forensic_evidence_get_failed session=%s err=%s", session_id, exc)
        return GenericResponse(success=False, message=str(exc), data=None)


@router.get("/{session_id}/bases-excerpt", response_model=GenericResponse)
async def get_forensic_risk_bases_excerpt(
    session_id: str,
    literal: str,
    page: Optional[int] = None,
    source: Optional[str] = None,
) -> GenericResponse:
    """Devuelve párrafo indexado de las bases para un literal de riesgo (HRU)."""
    memory = await get_connected_memory()
    try:
        if not literal or not str(literal).strip():
            return GenericResponse(success=False, message="Parámetro literal requerido", data=None)
        session_data = await memory.get_session(session_id) or {}
        from app.services.forensic_risk_bases_excerpt_service import fetch_bases_excerpt_v1

        excerpt = await fetch_bases_excerpt_v1(
            session_id,
            str(literal).strip(),
            page=page,
            source=source,
            session_state=session_data,
            memory=memory,
        )
        if not excerpt.get("available"):
            return GenericResponse(
                success=False,
                message=excerpt.get("user_message")
                or "No se encontró párrafo indexado para ese literal en la sesión",
                data=excerpt,
            )
        return GenericResponse(success=True, message="Extracto de bases", data=excerpt)
    except Exception as exc:
        logger.error("forensic_bases_excerpt_failed session=%s err=%s", session_id, exc)
        return GenericResponse(success=False, message=str(exc), data=None)


@router.get("/{session_id}/decisions", response_model=GenericResponse)
async def get_forensic_risk_decisions(session_id: str) -> GenericResponse:
    """Recupera riesgos enriquecidos + decisiones HITL."""
    memory = await get_connected_memory()
    try:
        session_data = await memory.get_session(session_id) or {}
        dictamen = session_data.get("dictamen")
        if not isinstance(dictamen, dict):
            return GenericResponse(success=False, message="No hay dictamen", data=None)
        dictamen = await attach_and_hydrate_forensic_risks(
            dictamen,
            session_id,
            session_state=session_data,
            memory=memory,
        )
        forensic_risks = dictamen.get("forensic_risks_v1") or {}
        record = session_data.get("risk_decisions_v1")
        merged = merge_risk_decisions_into_items(forensic_risks, record)
        return GenericResponse(
            success=True,
            message="Riesgos forenses recuperados",
            data={
                "forensic_risks_v1": merged,
                "risk_decisions_v1": record,
                "can_continue": can_continue_with_risks(forensic_risks, record),
            },
        )
    except Exception as exc:
        logger.error("forensic_risk_get_failed session=%s err=%s", session_id, exc)
        return GenericResponse(success=False, message=str(exc), data=None)
