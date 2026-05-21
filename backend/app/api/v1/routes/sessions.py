from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from app.api.deps import get_connected_memory
from app.config.settings import settings
from app.api.schemas.responses import GenericResponse
from app.checklist.models import MarkHitoPayload
from app.checklist.submission_checklist_service import (
    get_submission_checklist,
    mark_hito,
)
from app.post_clarification.models import (
    GenerateCarta33BisRequest,
    PostClarificationActaRequest,
)
from app.post_clarification.service import (
    generate_carta_33_bis,
    get_post_clarification_context,
    process_acta_document,
)
from app.economic_validation.service import (
    get_latest_analysis_and_economic,
    refresh_economic_validations_for_session,
)
from app.services.validation_service import validation_mapping_service
from app.services.validation_policy_service import resolve_validation_policy
import logging
from app.core.logging_config import get_logger
from app.services.vector_service import VectorDbServiceClient

class DictamenRequest(BaseModel):
    dictamen: Dict[str, Any]


class ValidationAcknowledgeRequest(BaseModel):
    error_type: str = Field(..., min_length=1)
    item_id: str | None = None


class ValidationJustificationRequest(BaseModel):
    action_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=3)
    item_id: str | None = None
    error_type: str | None = None


class ValidationTelemetryRequest(BaseModel):
    event: str = Field(..., min_length=1)
    error_type: str = Field(..., min_length=1)
    severity: str | None = None
    resolution_time_ms: int | None = None
    clicks_to_fix: int | None = None
    justification_length: int | None = None
    item_id: str | None = None


class ValidationPolicyUpdateRequest(BaseModel):
    policy: Dict[str, Any] = Field(..., description="Nuevo objeto validation_policy para la sesión")
    reason: str = Field(..., min_length=3, description="Motivo del cambio (auditoría)")
    updated_by: Optional[str] = Field(
        default=None,
        description="Usuario o sistema que realizó el cambio (para auditoría)",
    )


class EconomicZeroTotalBaseAckRequest(BaseModel):
    """HITL auditable: admite oferta con subtotal base cotizable bajo el umbral cuando las bases lo permiten."""

    confirm: bool = Field(..., description="Debe ser true para activar el reconocimiento")
    reason: str = Field(..., min_length=3, description="Cita o fundamento (auditoría)")


class ClearGeneratedOutputsRequest(BaseModel):
    """Confirmación explícita para borrar el expediente generado en disco."""

    confirm: bool = Field(
        ...,
        description="Debe ser true para ejecutar el borrado (evita clicks accidentales).",
    )


logger = get_logger(__name__)
router = APIRouter()

async def get_repository():
    return await get_connected_memory()


def _utc_iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

@router.get("", response_model=GenericResponse)
async def list_licitaciones():
    """Lista todas las licitaciones (sesiones) activas."""
    repo = await get_repository()
    try:
        sessions = await repo.list_sessions()
        return GenericResponse(
            success=True,
            message="Licitaciones recuperadas exitosamente",
            data={"licitaciones": sessions}
        )
    except Exception as e:
        logger.exception("Error listando sesiones")
        msg = str(e) if settings.ENVIRONMENT == "development" else "Error al recuperar licitaciones"
        raise HTTPException(status_code=500, detail=msg)
    finally:
        await repo.disconnect()

@router.post("/create", response_model=GenericResponse)
async def create_licitacion(name: str):
    """Crea una nueva licitacion (sesión)."""
    repo = await get_repository()
    # Limpiar nombre para id (ChromaDB compatible: 3-63 chars, alfanumérico + underscore/hyphen)
    import re
    session_id = re.sub(r'[^a-z0-9_-]', '', name.lower().replace(" ", "_"))
    # Asegurar longitud mínima y máxima
    if len(session_id) < 3:
        session_id = f"ses_{session_id}"
    session_id = session_id[:63]
    
    try:
        # Verificar si existe
        existing = await repo.get_session(session_id)
        if existing:
            return GenericResponse(success=False, message="Ya existe una licitación con ese nombre")
            
        await repo.save_session(session_id, {"created_by": "user", "name": name})
        return GenericResponse(
            success=True,
            message="Licitación creada",
            data={"session_id": session_id}
        )
    except Exception as e:
        logger.error(f"Error creando sesion: {e}")
        raise HTTPException(status_code=500, detail="Error al crear licitacion")
    finally:
        await repo.disconnect()

@router.delete("/{session_id}", response_model=GenericResponse)
async def delete_licitacion(session_id: str):
    repo = await get_repository()
    try:
        # 1. Borrar de Postgres
        success = await repo.delete_session(session_id)
        
        # 2. Borrar de ChromaDB
        if success:
            try:
                VectorDbServiceClient().delete_collection(session_id)
            except Exception as e:
                logger.warning(f"No se pudo borrar la colección Chroma para {session_id}: {e}")
                
        return GenericResponse(success=success, message="Licitación eliminada" if success else "No se pudo eliminar")
    finally:
        await repo.disconnect()

@router.get("/{session_id}/dictamen", response_model=GenericResponse)
async def get_dictamen(session_id: str):
    """Obtiene el dictamen consolidado de una sesión."""
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id)
        if session_data and "dictamen" in session_data:
            decision = session_data.get("last_orchestrator_decision") or {}
            last_quality_hints = session_data.get("last_document_quality_waiting_hints")
            last_fill_hints = session_data.get("last_document_fill_quality_waiting_hints")
            doc_candidates = session_data.get("document_candidates_consolidated") or session_data.get("document_candidates_final") or session_data.get("document_candidates_v1")
            if isinstance(doc_candidates, dict) and doc_candidates.get("sobre_1_tecnico") is not None:
                from app.services.document_deliverable_filter import (
                    filter_consolidated_document_candidates,
                )

                doc_candidates = filter_consolidated_document_candidates(doc_candidates)
            return GenericResponse(
                success=True,
                message="Dictamen recuperado",
                data={
                    "dictamen": session_data["dictamen"],
                    "go_no_go_result": session_data.get("go_no_go_result"),
                    "go_no_go_override": session_data.get("go_no_go_override"),
                    "stop_reason": decision.get("stop_reason"),
                    "last_document_quality_waiting_hints": last_quality_hints
                    if isinstance(last_quality_hints, dict)
                    else None,
                    "last_document_fill_quality_waiting_hints": last_fill_hints
                    if isinstance(last_fill_hints, dict)
                    else None,
                    "fast_track_document_candidates": doc_candidates if isinstance(doc_candidates, dict) else None,
                }
            )
        return GenericResponse(success=False, message="No hay dictamen guardado")
    except Exception as e:
        logger.error(f"Error recuperando dictamen: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar dictamen")
    finally:
        await repo.disconnect()

@router.post("/{session_id}/dictamen", response_model=GenericResponse)
async def save_dictamen(session_id: str, request: DictamenRequest):
    """Guarda el dictamen consolidado en la sesión (Postgres)."""
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id) or {}
        session_data["dictamen"] = request.dictamen
        ccc_in = request.dictamen.get("documentCandidatesConsolidated") if isinstance(request.dictamen, dict) else None
        if isinstance(ccc_in, dict) and ccc_in.get("sobre_1_tecnico") is not None:
            from app.services.document_deliverable_filter import (
                filter_consolidated_document_candidates,
            )

            filtered = filter_consolidated_document_candidates(ccc_in)
            session_data["document_candidates_consolidated"] = filtered
            session_data["dictamen"]["documentCandidatesConsolidated"] = filtered
        await repo.save_session(session_id, session_data)
        return GenericResponse(success=True, message="Dictamen guardado en Postgres exitosamente")
    except Exception as e:
        logger.error(f"Error guardando dictamen: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar dictamen en Postgres")
    finally:
        await repo.disconnect()

@router.get("/{session_id}/submission-checklist", response_model=GenericResponse)
async def get_submission_checklist_route(session_id: str):
    """Checklist de hitos del procedimiento (cronograma del Analista + marcas del usuario)."""
    repo = await get_repository()
    try:
        cl = await get_submission_checklist(repo, session_id, auto_sync=True)
        if not cl:
            return GenericResponse(
                success=False,
                message="No hay checklist: ejecute primero el análisis de bases o no existe la sesión.",
                data=None,
            )
        return GenericResponse(
            success=True,
            message="Submission checklist recuperado",
            data={"submission_checklist": cl.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error recuperando submission checklist: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar submission checklist")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/submission-checklist/{hito_id}/mark", response_model=GenericResponse)
async def mark_submission_hito(session_id: str, hito_id: str, payload: MarkHitoPayload):
    """Marca un hito como completado o pendiente y opcional evidencia (texto/referencia)."""
    repo = await get_repository()
    try:
        updated = await mark_hito(repo, session_id, hito_id, payload)
        if not updated:
            return GenericResponse(
                success=False,
                message="No se pudo actualizar el hito (id no encontrado o sin checklist).",
                data=None,
            )
        return GenericResponse(
            success=True,
            message="Hito actualizado",
            data={"submission_checklist": updated.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error marcando hito: {e}")
        raise HTTPException(status_code=500, detail="Error al marcar hito")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/checklist", response_model=GenericResponse)
async def get_checklist(session_id: str):
    """Obtiene la lista de verificación (checklist) de una sesión (Hito 7)."""
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id)
        if session_data and "checklist" in session_data:
            return GenericResponse(
                success=True,
                message="Checklist recuperado exitosamente",
                data={"checklist": session_data["checklist"]},
            )
        return GenericResponse(success=False, message="No hay checklist generado para esta sesión")
    except Exception as e:
        logger.error(f"Error recuperando checklist: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar checklist")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/post-clarification/acta", response_model=GenericResponse)
async def post_clarification_process_acta(
    session_id: str,
    payload: PostClarificationActaRequest,
):
    """
    Disparador explícito: procesa el PDF de acta ya subido (document_id) y persiste
    post_clarification_context en sesión.
    """
    repo = await get_repository()
    try:
        ctx = await process_acta_document(
            repo,
            session_id,
            payload.document_id,
            tipo_junta=payload.tipo_junta,
            correlation_id=f"{session_id}:post_clarification",
        )
        return GenericResponse(
            success=True,
            message="Acta procesada y contexto de post-aclaración actualizado.",
            data={"post_clarification_context": ctx.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error procesando acta de post-aclaración: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar acta: {str(e)}")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/post-clarification", response_model=GenericResponse)
async def get_post_clarification(session_id: str):
    repo = await get_repository()
    try:
        ctx = await get_post_clarification_context(repo, session_id)
        if not ctx:
            return GenericResponse(
                success=False,
                message="No existe contexto de post-aclaración para esta sesión.",
                data=None,
            )
        return GenericResponse(
            success=True,
            message="Contexto de post-aclaración recuperado.",
            data={"post_clarification_context": ctx.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error recuperando post-aclaración: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar post-aclaración")
    finally:
        await repo.disconnect()


@router.post(
    "/{session_id}/post-clarification/generate-carta-33-bis",
    response_model=GenericResponse,
)
async def post_clarification_generate_carta(
    session_id: str,
    payload: GenerateCarta33BisRequest,
):
    repo = await get_repository()
    try:
        ctx = await generate_carta_33_bis(
            repo,
            session_id,
            force_regenerate=payload.force_regenerate,
            correlation_id=f"{session_id}:carta_33_bis",
        )
        return GenericResponse(
            success=True,
            message="Carta 33 Bis generada/actualizada.",
            data={"post_clarification_context": ctx.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error generando carta 33 bis: {e}")
        raise HTTPException(status_code=500, detail=f"Error al generar carta: {str(e)}")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/economic-validations", response_model=GenericResponse)
async def get_economic_validations(session_id: str):
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        _analysis, economic = get_latest_analysis_and_economic(session)
        if not economic:
            return GenericResponse(
                success=False,
                message="No hay propuesta económica calculada en sesión.",
                data=None,
            )
        validation = economic.get("validation_result") if isinstance(economic, dict) else None
        return GenericResponse(
            success=bool(validation),
            message="Validaciones económicas recuperadas" if validation else "Sin validaciones económicas aún.",
            data={"validation_result": validation} if validation else None,
        )
    except Exception as e:
        logger.error(f"Error leyendo validaciones económicas: {e}")
        raise HTTPException(status_code=500, detail="Error al leer validaciones económicas")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/economic-validations/refresh", response_model=GenericResponse)
async def refresh_economic_validations(session_id: str):
    repo = await get_repository()
    try:
        result = await refresh_economic_validations_for_session(repo, session_id)
        return GenericResponse(
            success=True,
            message="Validaciones económicas recalculadas.",
            data={"validation_result": result.model_dump(mode="json")},
        )
    except Exception as e:
        logger.error(f"Error recalculando validaciones económicas: {e}")
        raise HTTPException(status_code=500, detail=f"Error refrescando validaciones: {str(e)}")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/economic-hitl/zero-total-base-ack", response_model=GenericResponse)
async def economic_zero_total_base_ack(session_id: str, payload: EconomicZeroTotalBaseAckRequest):
    """
    Registra confirmación explícita (HITL) para relajar la regla ``total_base_cotizable``
    en la sesión y, si existe ``economic_proposal``, recalcula validaciones.
    """
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="confirm debe ser true")
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id) or {}
        eu = dict(session.get("economic_user_inputs") or {})
        eu["allow_zero_total_base_ack"] = True
        eu["allow_zero_total_base_ack_reason"] = str(payload.reason).strip()[:4000]
        eu["allow_zero_total_base_ack_at"] = _utc_iso_now()
        session["economic_user_inputs"] = eu
        await repo.save_session(session_id, session)
        try:
            result = await refresh_economic_validations_for_session(repo, session_id)
            vr = result.model_dump(mode="json")
        except Exception as _refr:
            logger.info(
                "economic_zero_total_base_ack_refresh_skipped",
                session_id=session_id,
                error=str(_refr),
            )
            vr = None
        return GenericResponse(
            success=True,
            message="Confirmación HITL registrada para oferta sin importe base positivo.",
            data={"allow_zero_total_base_ack": True, "validation_result": vr},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error guardando ack zero total base: {e}")
        raise HTTPException(status_code=500, detail="Error guardando confirmación económica")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/validation-events/ack", response_model=GenericResponse)
async def acknowledge_validation_warning(session_id: str, payload: ValidationAcknowledgeRequest):
    """Registra ack de advertencia de validacion por sesion."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id) or {}
        state = session.get("user_validation_state") or {}
        ack_list = list(state.get("acknowledged_warnings") or [])
        entry = {
            "error_type": payload.error_type,
            "item_id": payload.item_id,
            "acknowledged_at": _utc_iso_now(),
        }
        ack_list.append(entry)
        state["acknowledged_warnings"] = ack_list
        session["user_validation_state"] = state
        await repo.save_session(session_id, session)
        return GenericResponse(success=True, message="Advertencia reconocida", data={"acknowledged": entry})
    except Exception as e:
        logger.error(f"Error guardando acknowledge de validacion: {e}")
        raise HTTPException(status_code=500, detail="Error guardando acknowledge")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/validation-events/justify", response_model=GenericResponse)
async def save_validation_justification(session_id: str, payload: ValidationJustificationRequest):
    """Guarda justificacion de usuario para acciones de validacion."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id) or {}
        state = session.get("user_validation_state") or {}
        just_list = list(state.get("justifications") or [])
        entry = {
            "action_id": payload.action_id,
            "error_type": payload.error_type,
            "item_id": payload.item_id,
            "reason": payload.reason,
            "created_at": _utc_iso_now(),
        }
        just_list.append(entry)
        state["justifications"] = just_list
        session["user_validation_state"] = state
        await repo.save_session(session_id, session)
        return GenericResponse(success=True, message="Justificacion guardada", data={"justification": entry})
    except Exception as e:
        logger.error(f"Error guardando justificacion de validacion: {e}")
        raise HTTPException(status_code=500, detail="Error guardando justificacion")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/validation-telemetry", response_model=GenericResponse)
async def save_validation_telemetry(session_id: str, payload: ValidationTelemetryRequest):
    """Persiste eventos minimos de telemetria de interaccion de validaciones."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id) or {}
        telemetry = list(session.get("validation_telemetry") or [])
        entry = {
            "event": payload.event,
            "error_type": payload.error_type,
            "severity": payload.severity,
            "resolution_time_ms": payload.resolution_time_ms,
            "clicks_to_fix": payload.clicks_to_fix,
            "justification_length": payload.justification_length,
            "item_id": payload.item_id,
            "created_at": _utc_iso_now(),
        }
        telemetry.append(entry)
        session["validation_telemetry"] = telemetry[-300:]
        await repo.save_session(session_id, session)
        return GenericResponse(success=True, message="Telemetria guardada", data={"telemetry": entry})
    except Exception as e:
        logger.error(f"Error guardando telemetria de validacion: {e}")
        raise HTTPException(status_code=500, detail="Error guardando telemetria")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/validation-policy", response_model=GenericResponse)
async def get_validation_policy(session_id: str):
    """Obtiene la política dinámica de validación y su historial (si existe)."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        policy = session.get("validation_policy") or {}
        history = session.get("validation_policy_history") or []
        return GenericResponse(
            success=True,
            message="Política de validación recuperada",
            data={"validation_policy": policy, "history": history},
        )
    except Exception as e:
        logger.error(f"Error leyendo validation_policy: {e}")
        raise HTTPException(status_code=500, detail="Error al leer política de validación")
    finally:
        await repo.disconnect()


@router.put("/{session_id}/validation-policy", response_model=GenericResponse)
async def update_validation_policy(session_id: str, payload: ValidationPolicyUpdateRequest):
    """
    Actualiza la política dinámica de validación de una sesión y registra historial.
    """
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id) or {}
        old_policy = session.get("validation_policy") or {}
        history: List[Dict[str, Any]] = list(session.get("validation_policy_history") or [])

        entry = {
            "previous_policy": old_policy,
            "new_policy": payload.policy,
            "reason": payload.reason,
            "updated_by": payload.updated_by or "ui-admin",
            "updated_at": _utc_iso_now(),
        }
        history.append(entry)
        # Mantener solo últimos 50 cambios por sesión
        session["validation_policy_history"] = history[-50:]
        session["validation_policy"] = payload.policy

        await repo.save_session(session_id, session)
        return GenericResponse(
            success=True,
            message="Política de validación actualizada",
            data={"validation_policy": payload.policy, "last_change": entry},
        )
    except Exception as e:
        logger.error(f"Error actualizando validation_policy: {e}")
        raise HTTPException(status_code=500, detail="Error al actualizar política de validación")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/validation-events/revalidate", response_model=GenericResponse)
async def revalidate_validation_events(session_id: str):
    """
    Revalida reglas economicas y devuelve eventos UX actualizados.

    Permite cerrar bloqueos por estado real de validacion (no por click).
    """
    repo = await get_repository()
    try:
        session_state = await repo.get_session(session_id) or {}
        result = await refresh_economic_validations_for_session(repo, session_id)
        events: list[dict[str, Any]] = []
        for issue in list(result.blocking_issues or []):
            error_type = str(issue).split(":", 1)[0].strip().lower()
            if not error_type:
                error_type = "economic_validation_blocking"
            ctx: Dict[str, Any] = {"session_id": session_id}
            traz = result.trazabilidad.get(error_type)
            if isinstance(traz, dict):
                valor = traz.get("valor_calculado")
                if isinstance(valor, dict):
                    ctx.update(valor)
                elif isinstance(valor, list) and valor:
                    ctx["item_name"] = str(valor[0])
                    ctx["raw_value"] = 0
            policy = resolve_validation_policy(session_state, error_type=error_type)
            events.append(
                validation_mapping_service.build_event(
                    error_type=error_type,
                    context=ctx,
                    raw_message=issue,
                    policy=policy,
                )
            )
        return GenericResponse(
            success=True,
            message="Revalidacion economica completada.",
            data={
                "validation_result": result.model_dump(mode="json"),
                "validation_events": events,
                "blocking_count": len(result.blocking_issues or []),
                "policy_preview": {
                    et: resolve_validation_policy(session_state, error_type=et)
                    for et in {str(i).split(":", 1)[0].strip().lower() for i in list(result.blocking_issues or [])}
                },
            },
        )
    except Exception as e:
        logger.error(f"Error revalidando validation events: {e}")
        raise HTTPException(status_code=500, detail=f"Error revalidando eventos: {str(e)}")
    finally:
        await repo.disconnect()


@router.delete("/{session_id}/generated-outputs", response_model=GenericResponse)
async def clear_generated_outputs_route(
    session_id: str,
    body: ClearGeneratedOutputsRequest,
):
    """
    Elimina Word/ZIP/sobres bajo ``/data/outputs/{sesión}`` y resetea marcas de generación.

    No elimina dictamen, candidatos CCC ni PDFs de bases subidos.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Debes enviar confirm=true para limpiar el expediente generado.",
        )
    try:
        from app.services.generated_outputs_cleanup import (
            clear_generated_outputs_for_session,
        )

        result = await clear_generated_outputs_for_session(session_id)
        n = result.get("removed_count", 0)
        return GenericResponse(
            success=True,
            message=(
                f"Expediente generado eliminado ({n} elemento(s) en disco). "
                "Puedes volver a pulsar «GENERAR PROPUESTA»."
            ),
            data=result,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    except OSError as e:
        logger.error("clear_generated_outputs_failed", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail="No se pudo eliminar el expediente en disco. Revisa permisos del volumen.",
        )
    except Exception as e:
        logger.error(f"Error limpiando expediente generado: {e}")
        raise HTTPException(status_code=500, detail="Error al limpiar expediente generado")


@router.get("/{session_id}/delivery-checklist", response_model=GenericResponse)
async def get_delivery_checklist(session_id: str):
    """
    Obtiene la Guía de Armado y Checklist de Integridad compilada por el BiddingBinderAgent.
    """
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
            
        checklist = session.get("delivery_checklist")
        if not checklist:
            # Si no existe, podemos generarlo o devolver que no está listo
            return GenericResponse(
                success=False, 
                message="El checklist de entrega final aún no ha sido compilado por el BiddingBinderAgent.", 
                data=None
            )
            
        return GenericResponse(
            success=True,
            message="Checklist de entrega final recuperado",
            data={"delivery_checklist": checklist}
        )
    except Exception as e:
        logger.error(f"Error recuperando delivery checklist: {e}")
        raise HTTPException(status_code=500, detail="Error al recuperar checklist de entrega final")
    finally:
        await repo.disconnect()
