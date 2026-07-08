from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse
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
from app.services.mini_dictamen_anexos_service import (
    build_and_persist_mini_dictamen,
    resolve_clarification_ticket,
)
from app.services.junta_aclaraciones_questions_service import (
    build_and_persist_junta_aclaraciones_questions,
    mini_dictamen_needs_co_refresh,
    bundle_needs_regeneration,
    _enrich_session_for_junta,
    format_junta_questions_plain_text,
    update_junta_question_status,
)
from app.contracts.junta_aclaraciones_questions import JuntaAclaracionesQuestionsBundle
import logging
import os
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


class BindCompanyRequest(BaseModel):
    """Ligado transaccional de empresa a sesión (HRU R2)."""

    company_id: str = Field(..., min_length=1, description="ID de empresa en catálogo")


class ClearGeneratedOutputsRequest(BaseModel):
    """Confirmación explícita para borrar el expediente generado en disco."""

    confirm: bool = Field(
        ...,
        description="Debe ser true para ejecutar el borrado (evita clicks accidentales).",
    )


class JuntaQuestionStatusRequest(BaseModel):
    status: str = Field(
        ...,
        description="borrador | aprobada | enviada | excluida",
    )


class ClarificationTicketResolveRequest(BaseModel):
    status: str = Field(
        default="resolved",
        description="Nuevo estado del ticket: open, ready_for_junta, answered, waived, resolved.",
    )
    resolution_note: str = Field(
        default="",
        description="Nota auditable de resolución o criterio aplicado.",
    )
    resolution_source: Optional[str] = Field(
        default=None,
        description="Origen de la resolución (manual, acta, junta, sistema).",
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
            dictamen_out = session_data["dictamen"]
            if isinstance(dictamen_out, dict):
                try:
                    from app.services.forensic_risk_service import (
                        attach_and_hydrate_forensic_risks,
                        merge_risk_decisions_into_items,
                    )

                    dictamen_out = await attach_and_hydrate_forensic_risks(
                        dictamen_out,
                        session_id,
                        session_state=session_data,
                        memory=repo,
                    )
                    risk_decisions = session_data.get("risk_decisions_v1")
                    if dictamen_out.get("forensic_risks_v1"):
                        dictamen_out["forensic_risks_v1"] = merge_risk_decisions_into_items(
                            dictamen_out["forensic_risks_v1"],
                            risk_decisions,
                        )
                except Exception as risk_exc:
                    logger.warning(
                        "dictamen_forensic_risks_skip session=%s err=%s",
                        session_id,
                        risk_exc,
                    )
                try:
                    from app.utils.audit_processor import strip_stale_tabular_alert_from_dictamen

                    rows = await repo.get_line_items_for_session(session_id)
                    n_li = len(rows or [])
                    if n_li > 0:
                        dictamen_out = strip_stale_tabular_alert_from_dictamen(
                            dictamen_out, n_li
                        )
                except Exception as tab_exc:
                    logger.warning(
                        "dictamen_tabular_sanitize_skip session=%s err=%s",
                        session_id,
                        tab_exc,
                    )
                try:
                    from app.config.settings import settings
                    from app.services.dictamen_curation_service import (
                        refresh_dictamen_curation_if_needed,
                    )

                    if settings.DICTAMEN_CURATION_ENABLED and isinstance(dictamen_out, dict):
                        dictamen_out = refresh_dictamen_curation_if_needed(
                            dictamen_out,
                            session_state=session_data,
                            extraction_health=dictamen_out.get("extractionHealth"),
                            compliance=session_data.get("compliance"),
                            view_mode=str(settings.DICTAMEN_VIEW_MODE or "licitante"),
                            curation_enabled=True,
                        )
                except Exception as cur_exc:
                    logger.warning(
                        "dictamen_curation_refresh_skip session=%s err=%s",
                        session_id,
                        cur_exc,
                    )
            decision = session_data.get("last_orchestrator_decision") or {}
            last_quality_hints = session_data.get("last_document_quality_waiting_hints")
            last_fill_hints = session_data.get("last_document_fill_quality_waiting_hints")
            doc_candidates = session_data.get("document_candidates_consolidated") or session_data.get("document_candidates_final") or session_data.get("document_candidates_v1")
            needs_rebuild = (
                not doc_candidates
                or (
                    isinstance(doc_candidates, dict)
                    and doc_candidates.get("sobre_1_tecnico") is None
                    and not doc_candidates.get("candidate_document_list")
                )
            )
            if needs_rebuild and session_data.get("compliance_master_list"):
                try:
                    from app.services.document_candidate_list_service import (
                        ensure_session_document_candidates,
                    )

                    rebuilt = await ensure_session_document_candidates(
                        repo, session_id, session_data
                    )
                    if rebuilt:
                        doc_candidates = rebuilt
                        session_data = await repo.get_session(session_id) or session_data
                except Exception as rebuild_exc:
                    logger.warning(
                        "dictamen_rebuild_document_candidates_failed session=%s err=%s",
                        session_id,
                        rebuild_exc,
                    )
            formats_panel_payload = None
            try:
                from app.services.document_candidate_list_service import (
                    build_formats_panel_consolidated,
                )

                formats_panel_payload = await build_formats_panel_consolidated(
                    repo, session_id, session_data
                )
            except Exception as fmt_exc:
                logger.warning(
                    "dictamen_formats_panel_failed session=%s err=%s",
                    session_id,
                    fmt_exc,
                )
            if isinstance(formats_panel_payload, dict) and formats_panel_payload.get(
                "sobre_1_tecnico"
            ) is not None:
                doc_candidates = formats_panel_payload
            elif isinstance(doc_candidates, dict) and doc_candidates.get("sobre_1_tecnico") is not None:
                from app.services.document_deliverable_filter import (
                    filter_consolidated_document_candidates,
                )

                doc_candidates = filter_consolidated_document_candidates(doc_candidates)
            submission_checklist_payload = None
            corporate_physical_payload = None
            try:
                from app.checklist.submission_checklist_service import (
                    checklist_ready_without_enrichment,
                    ensure_session_cronograma_and_checklist,
                    get_submission_checklist,
                )

                if checklist_ready_without_enrichment(session_data):
                    cl = await get_submission_checklist(
                        repo, session_id, refresh_placeholders=False
                    )
                else:
                    cl = await ensure_session_cronograma_and_checklist(repo, session_id)
                if cl:
                    submission_checklist_payload = cl.model_dump(mode="json")
            except Exception as cl_exc:
                logger.warning(
                    "dictamen_submission_checklist_failed session=%s err=%s",
                    session_id,
                    cl_exc,
                )
            try:
                from app.services.document_candidate_list_service import (
                    build_corporate_physical_panel_list,
                )

                corporate_physical_payload = await build_corporate_physical_panel_list(
                    repo, session_id, session_data
                )
            except Exception as corp_exc:
                logger.warning(
                    "dictamen_corporate_physical_failed session=%s err=%s",
                    session_id,
                    corp_exc,
                )
            return GenericResponse(
                success=True,
                message="Dictamen recuperado",
                data={
                    "dictamen": dictamen_out,
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
                    "pliego_formats_panel": doc_candidates if isinstance(doc_candidates, dict) else None,
                    "submission_checklist": submission_checklist_payload,
                    "corporate_physical_document_candidates": corporate_physical_payload,
                    "risk_decisions_v1": session_data.get("risk_decisions_v1"),
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
        from app.checklist.submission_checklist_service import (
            ensure_session_cronograma_and_checklist,
        )

        cl = await ensure_session_cronograma_and_checklist(repo, session_id)
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


@router.get("/{session_id}/document-candidates-summary", response_model=GenericResponse)
async def get_document_candidates_summary(session_id: str):
    """
    Credenciales empresariales para presentación física (panel ligero, sin dictamen completo).
    """
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id)
        if not session_data:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        from app.services.document_candidate_list_service import (
            build_corporate_physical_panel_list,
        )

        payload = await build_corporate_physical_panel_list(repo, session_id, session_data)
        if not isinstance(payload, dict):
            payload = {"candidate_document_list": [], "_meta": {"total": 0}}
        return GenericResponse(
            success=True,
            message="Documentos corporativos recuperados",
            data={"corporate_physical_document_candidates": payload},
        )
    except Exception as e:
        logger.error(
            "document_candidates_summary_failed session=%s err=%s",
            session_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail="Error al recuperar documentos corporativos detectados",
        )
    finally:
        await repo.disconnect()


@router.get("/{session_id}/pliego-formats-panel", response_model=GenericResponse)
async def get_pliego_formats_panel(session_id: str):
    """
    Formatos y anexos del pliego por sobre (panel ligero, sin dictamen completo).
    """
    repo = await get_repository()
    try:
        session_data = await repo.get_session(session_id)
        if not session_data:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        from app.services.document_candidate_list_service import (
            build_formats_panel_consolidated,
        )

        payload = await build_formats_panel_consolidated(repo, session_id, session_data)
        if not isinstance(payload, dict):
            payload = {
                "sobre_1_tecnico": [],
                "sobre_2_economico": [],
                "_meta": {"total": 0},
            }
        return GenericResponse(
            success=True,
            message="Formatos detectados recuperados",
            data={"pliego_formats_panel": payload},
        )
    except Exception as e:
        logger.error(
            "pliego_formats_panel_failed session=%s err=%s",
            session_id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail="Error al recuperar formatos detectados",
        )
    finally:
        await repo.disconnect()


@router.get("/{session_id}/health", response_model=GenericResponse)
async def get_session_health(session_id: str):
    """
    Salud de artefactos de análisis (conteos, stale, recomendación de rehidratación).
    Lectura ligera: no ejecuta enrichment RAG ni rebuild pesado.
    """
    repo = await get_repository()
    try:
        from app.services.session_health_service import assess_session_health

        state = await repo.get_session(session_id)
        if not state:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        payload = assess_session_health(session_id, state)
        return GenericResponse(
            success=True,
            message="Salud de sesión evaluada",
            data={"session_health": payload},
        )
    except Exception as e:
        logger.error("session_health_failed session=%s err=%s", session_id, e)
        raise HTTPException(status_code=500, detail="Error al evaluar salud de sesión")
    finally:
        await repo.disconnect()


class RehydrateArtifactsRequest(BaseModel):
    company_id: Optional[str] = None
    force_junta: bool = False
    sync: bool = False


@router.post("/{session_id}/rehydrate-analysis-artifacts", response_model=GenericResponse)
async def post_rehydrate_analysis_artifacts(
    session_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[RehydrateArtifactsRequest] = None,
    sync: bool = Query(False, description="Ejecución síncrona (scripts); default async job"),
):
    """
    Reconstruye candidatos, hitos, junta y confirma snapshot.

    Por defecto encola job async (202 + job_id) para no bloquear el worker HTTP.
    ``sync=true`` o body.sync=true ejecuta en la petición (compat scripts).
    """
    repo = await get_repository()
    try:
        state = await repo.get_session(session_id)
        if not state:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)

        req = body or RehydrateArtifactsRequest()
        run_sync = bool(sync or req.sync)

        if not run_sync:
            from app.services.job_service import get_active_session_maintenance_job
            from app.services.session_maintenance_job_service import (
                create_rehydrate_job,
                run_rehydrate_job_in_thread,
            )

            active = get_active_session_maintenance_job(session_id)
            if active.get("job_id"):
                return JSONResponse(
                    status_code=202,
                    content=GenericResponse(
                        success=True,
                        message="Rehidratación ya en curso",
                        data={
                            "job_id": active["job_id"],
                            "session_id": session_id,
                            "async": True,
                        },
                    ).model_dump(),
                )

            job_id = create_rehydrate_job(session_id)
            background_tasks.add_task(
                run_rehydrate_job_in_thread,
                job_id,
                session_id,
                company_id=req.company_id,
                force_junta=bool(req.force_junta),
            )
            return JSONResponse(
                status_code=202,
                content=GenericResponse(
                    success=True,
                    message="Rehidratación encolada",
                    data={
                        "job_id": job_id,
                        "session_id": session_id,
                        "async": True,
                        "poll_url": f"/api/v1/agents/jobs/{job_id}/status",
                    },
                ).model_dump(),
            )

        from app.services.analysis_artifacts_rehydrate_service import (
            rehydrate_after_analysis_pipeline,
        )
        from app.services.session_health_service import assess_session_health

        result = await rehydrate_after_analysis_pipeline(
            repo,
            session_id,
            company_id=req.company_id,
            commit_snapshot=True,
            force_junta_refresh=bool(req.force_junta),
        )
        fresh = await repo.get_session(session_id) or state
        health = assess_session_health(session_id, fresh)
        return GenericResponse(
            success=result.success,
            message="Rehidratación completada" if result.success else "Rehidratación incompleta",
            data={
                "rehydrate": result.to_dict(),
                "session_health": health,
                "async": False,
            },
        )
    except Exception as e:
        logger.error("rehydrate_analysis_artifacts_failed session=%s err=%s", session_id, e)
        raise HTTPException(status_code=500, detail="Error al rehidratar artefactos")
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


@router.get("/{session_id}/coverage-report", response_model=GenericResponse)
async def get_coverage_report(session_id: str, refresh: bool = False):
    """
    Reporte universal de cobertura: plantillas ingestadas vs entregables generados.

    ``refresh=true`` recalcula catálogo y matriz desde documentos y manifiesto actuales.
    """
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)

        if refresh:
            from app.services.delivery_coverage_report import build_and_persist_coverage

            report = await build_and_persist_coverage(repo, session_id)
            catalog = (await repo.get_session(session_id) or {}).get(
                "session_template_catalog"
            )
        else:
            report = session.get("delivery_coverage_report")
            catalog = session.get("session_template_catalog")
            if not report:
                from app.services.delivery_coverage_report import build_and_persist_coverage

                report = await build_and_persist_coverage(repo, session_id)
                catalog = (await repo.get_session(session_id) or {}).get(
                    "session_template_catalog"
                )

        return GenericResponse(
            success=True,
            message="Reporte de cobertura de entrega",
            data={
                "delivery_coverage_report": report,
                "session_template_catalog": catalog,
            },
        )
    except Exception as e:
        logger.error("coverage_report_failed", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=500, detail="Error al generar reporte de cobertura"
        )
    finally:
        await repo.disconnect()


@router.get("/{session_id}/document-catalog", response_model=GenericResponse)
async def get_document_catalog(session_id: str, refresh: bool = False):
    """
    Catálogo de fuentes clasificadas (rol, casos de uso, entidades, procedencia).

    ``refresh=true`` reconstruye desde todos los documentos ANALYZED de la sesión.
    """
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)

        if refresh:
            from app.services.document_catalog_service import refresh_session_document_catalog

            catalog = await refresh_session_document_catalog(repo, session_id)
        else:
            catalog = session.get("document_catalog")
            if not catalog:
                from app.services.document_catalog_service import refresh_session_document_catalog

                catalog = await refresh_session_document_catalog(repo, session_id)

        return GenericResponse(
            success=True,
            message="Catálogo de fuentes de sesión",
            data={"document_catalog": catalog},
        )
    except Exception as e:
        logger.error("document_catalog_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al obtener catálogo de fuentes")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/capture-matrix-blocks", response_model=GenericResponse)
async def get_capture_matrix_blocks(session_id: str):
    """Bloques de matriz orientadora para captura económica (Ítem D)."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        from app.services.economic_capture_matrix_service import (
            build_capture_matrix_blocks_from_pending,
            economic_capture_status,
            hydrate_matrix_blocks_with_inputs,
        )

        blocks = hydrate_matrix_blocks_with_inputs(
            session.get("capture_matrix_blocks") or [],
            session.get("economic_user_inputs"),
        )
        if not blocks:
            rebuilt = build_capture_matrix_blocks_from_pending(
                list(session.get("pending_questions") or []),
                session.get("economic_user_inputs"),
            )
            if rebuilt:
                blocks = hydrate_matrix_blocks_with_inputs(
                    rebuilt, session.get("economic_user_inputs")
                )
        cap = economic_capture_status({**session, "capture_matrix_blocks": blocks})
        from app.services.expediente_guided_service import (
            economic_capture_honest_status,
            expediente_guided_enabled,
            resolve_expediente_guided_state,
        )

        if expediente_guided_enabled():
            cap = economic_capture_honest_status({**session, "capture_matrix_blocks": blocks})
        from app.services.economic_capture_matrix_service import (
            build_capture_matrix_meta,
            format_capture_summary_message,
        )

        meta = session.get("capture_matrix_meta")
        if not isinstance(meta, dict) or not meta:
            meta = build_capture_matrix_meta(
                blocks, list(session.get("session_line_items") or [])
            )
        excel_tsv = ""
        if blocks:
            from app.services.chat_economic_matrix import format_matrix_blocks_excel_tsv

            excel_tsv = format_matrix_blocks_excel_tsv(blocks)
        return GenericResponse(
            success=True,
            message="Matriz de captura económica",
            data={
                "blocks": blocks,
                "count": len(blocks),
                "excel_clipboard_tsv": excel_tsv,
                "capture_status": cap,
                "capture_summary": format_capture_summary_message(
                    cap,
                    economic_validated=bool(
                        (session.get("expediente_guided_v1") or {}).get("economic_validated_at")
                    ),
                ),
                "capture_matrix_meta": meta,
                "expediente_guided": resolve_expediente_guided_state(session)
                if expediente_guided_enabled()
                else None,
            },
        )
    except Exception as e:
        logger.error("capture_matrix_blocks_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al leer matriz de captura")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/expediente-guided", response_model=GenericResponse)
async def get_expediente_guided(session_id: str, analysis_done: bool = Query(False)):
    """Estado P0 del expediente guiado (pasos, CTA, etiquetas panel)."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        from app.services.expediente_guided_service import (
            expediente_guided_enabled,
            resolve_expediente_guided_state,
        )

        if not expediente_guided_enabled():
            return GenericResponse(
                success=True,
                message="Expediente guiado deshabilitado",
                data={"enabled": False},
            )
        session = dict(session)
        session["session_id"] = session_id
        company_profile = None
        company_exists = None
        company_id = str(session.get("company_id") or "").strip()
        if company_id:
            company_row = await repo.get_company(company_id)
            if company_row:
                company_exists = True
                company_profile = company_row.get("master_profile") or company_row
            else:
                company_exists = False
        output_root = os.path.join("/data/outputs", session_id)
        if not os.path.isdir(output_root):
            output_root = None
        payload = resolve_expediente_guided_state(
            session,
            analysis_done_hint=bool(analysis_done),
            company_profile=company_profile if isinstance(company_profile, dict) else None,
            company_exists=company_exists,
            session_output_path=output_root,
        )
        return GenericResponse(success=True, message="Expediente guiado", data=payload)
    except Exception as e:
        logger.error("expediente_guided_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al leer expediente guiado")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/readiness", response_model=GenericResponse)
async def get_expediente_readiness(session_id: str):
    """
    Verdad canónica de readiness — captura, generación y entrega segura (HRU).

    Fuente única para orquestador, descargas y (futuro) UI.
    """
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)

        session = dict(session)
        session["session_id"] = session_id

        company_profile = None
        company_exists = None
        company_id = str(session.get("company_id") or "").strip()
        if company_id:
            company_row = await repo.get_company(company_id)
            if company_row:
                company_exists = True
                company_profile = company_row.get("master_profile") or company_row
            else:
                company_exists = False

        output_root = os.path.join("/data/outputs", session_id)
        if not os.path.isdir(output_root):
            output_root = None

        from app.services.expediente_readiness_service import resolve_expediente_readiness

        payload = resolve_expediente_readiness(
            session,
            company_profile=company_profile if isinstance(company_profile, dict) else None,
            company_exists=company_exists,
            session_output_path=output_root,
        )
        return GenericResponse(success=True, message="Expediente readiness", data=payload)
    except Exception as e:
        logger.error("expediente_readiness_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al evaluar readiness del expediente")
    finally:
        await repo.disconnect()


@router.post("/{session_id}/bind-company", response_model=GenericResponse)
async def bind_company_route(session_id: str, body: BindCompanyRequest):
    """
    Liga empresa del catálogo a la sesión e invalida artefactos incoherentes (HRU R2).

    Al cambiar de empresa: borra outputs económicos en disco, invalida snapshot y resetea jobs.
    """
    repo = await get_repository()
    try:
        from app.services.company_binding_service import bind_company_to_session

        result = await bind_company_to_session(repo, session_id, body.company_id.strip())
        msg = (
            "Empresa ligada correctamente."
            if not result.get("company_changed")
            else "Empresa actualizada; se invalidaron artefactos económicos previos."
        )
        return GenericResponse(success=True, message=msg, data=result)
    except ValueError as e:
        err = str(e)
        if "SESSION_NOT_FOUND" in err or "no encontrada" in err.lower():
            raise HTTPException(status_code=404, detail=err)
        if "COMPANY_NOT_FOUND" in err or "no existe" in err.lower():
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=400, detail=err)
    except OSError as e:
        logger.error("bind_company_disk_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al limpiar artefactos económicos en disco")
    except Exception as e:
        logger.error("bind_company_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al ligar empresa a la sesión")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/mini-dictamen-anexos", response_model=GenericResponse)
async def get_mini_dictamen_anexos(session_id: str, refresh: bool = False):
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        if refresh or not isinstance(session.get("mini_dictamen_anexos"), dict):
            mini = await build_and_persist_mini_dictamen(repo, session_id)
            session = await repo.get_session(session_id) or session
            payload = mini.model_dump(mode="json")
        else:
            payload = session.get("mini_dictamen_anexos")
        return GenericResponse(
            success=True,
            message="Mini dictamen de anexos recuperado",
            data={
                "mini_dictamen_anexos": payload,
                "clarification_tickets": session.get("clarification_tickets") or payload.get("clarification_tickets") or [],
            },
        )
    except Exception as e:
        logger.error("mini_dictamen_anexos_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al recuperar mini dictamen de anexos")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/convocatoria-briefing", response_model=GenericResponse)
async def get_convocatoria_briefing(session_id: str, refresh: bool = False):
    """Briefing HRU F11: qué solicita la convocante (tres bloques + primer paso)."""
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        from app.services.convocatoria_briefing_service import (
            convocatoria_briefing_enabled,
            merge_convocatoria_briefing_v1,
        )
        from app.services.convocatoria_briefing_ux import render_panel_briefing_summary

        if not convocatoria_briefing_enabled():
            return GenericResponse(
                success=True,
                message="Briefing deshabilitado por configuración",
                data={"enabled": False},
            )
        updates = merge_convocatoria_briefing_v1(session) if refresh or not session.get("convocatoria_briefing_v1") else {}
        if updates:
            await repo.save_session(session_id, updates)
            session = {**session, **updates}
        briefing = session.get("convocatoria_briefing_v1") or {}
        return GenericResponse(
            success=True,
            message="Briefing de convocatoria recuperado",
            data={
                "convocatoria_briefing_v1": briefing,
                "panel_summary": render_panel_briefing_summary(briefing),
            },
        )
    except Exception as e:
        logger.error("convocatoria_briefing_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al recuperar briefing de convocatoria")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/clarification-tickets", response_model=GenericResponse)
async def get_clarification_tickets(session_id: str, refresh: bool = False):
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        if refresh or not isinstance(session.get("clarification_tickets"), list):
            mini = await build_and_persist_mini_dictamen(repo, session_id)
            tickets = [t.model_dump(mode="json") for t in mini.clarification_tickets]
        else:
            tickets = list(session.get("clarification_tickets") or [])
        return GenericResponse(
            success=True,
            message="Tickets de aclaración recuperados",
            data={"clarification_tickets": tickets},
        )
    except Exception as e:
        logger.error("clarification_tickets_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al recuperar clarification tickets")
    finally:
        await repo.disconnect()


@router.post(
    "/{session_id}/clarification-tickets/{ticket_id}/resolve",
    response_model=GenericResponse,
)
async def resolve_clarification_ticket_route(
    session_id: str,
    ticket_id: str,
    payload: ClarificationTicketResolveRequest,
):
    allowed = {"open", "ready_for_junta", "answered", "waived", "resolved"}
    status = str(payload.status or "").strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Estado de clarification ticket inválido")
    repo = await get_repository()
    try:
        ticket = await resolve_clarification_ticket(
            repo,
            session_id,
            ticket_id,
            status=status,
            resolution_note=payload.resolution_note,
            resolution_source=payload.resolution_source or "manual",
        )
        session = await repo.get_session(session_id) or {}
        return GenericResponse(
            success=True,
            message="Clarification ticket actualizado",
            data={
                "clarification_ticket": ticket.model_dump(mode="json"),
                "mini_dictamen_anexos": session.get("mini_dictamen_anexos"),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("clarification_ticket_resolve_failed", session_id=session_id, ticket_id=ticket_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al resolver clarification ticket")
    finally:
        await repo.disconnect()


@router.get("/{session_id}/junta-aclaraciones-questions", response_model=GenericResponse)
async def get_junta_aclaraciones_questions(
    session_id: str,
    refresh: bool = False,
    format: str = "json",
    company_id: Optional[str] = None,
):
    """
    Listado unificado de preguntas para la convocante (junta de aclaraciones).
  Use ``refresh=true`` para recalcular desde analista, evidencia y mini dictamen.
    """
    repo = await get_repository()
    try:
        session = await repo.get_session(session_id)
        if not session:
            return GenericResponse(success=False, message="Sesión no encontrada", data=None)
        enriched = await _enrich_session_for_junta(
            repo, session_id, session, company_id=company_id
        )
        stored = session.get("junta_aclaraciones_questions")
        try:
            documents = await repo.get_documents(session_id)
        except Exception:
            documents = []
        needs_rebuild = refresh or bundle_needs_regeneration(
            stored if isinstance(stored, dict) else None,
            session_state=enriched,
        ) or mini_dictamen_needs_co_refresh(session_id, enriched, documents)
        if needs_rebuild:
            bundle = await build_and_persist_junta_aclaraciones_questions(
                repo,
                session_id,
                session_state=enriched,
                company_id=company_id,
                force_refresh=bool(refresh),
            )
            payload = bundle.model_dump(mode="json")
        else:
            payload = stored
        if str(format or "").lower() in ("text", "plain", "txt"):
            bundle = JuntaAclaracionesQuestionsBundle.model_validate(payload)
            return GenericResponse(
                success=True,
                message="Listado para junta (texto)",
                data={
                    "junta_aclaraciones_questions": payload,
                    "plain_text": format_junta_questions_plain_text(bundle),
                },
            )
        return GenericResponse(
            success=True,
            message="Listado para junta de aclaraciones",
            data={"junta_aclaraciones_questions": payload},
        )
    except Exception as e:
        logger.error("junta_aclaraciones_questions_failed", session_id=session_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error al obtener preguntas para la junta")
    finally:
        await repo.disconnect()


@router.post(
    "/{session_id}/junta-aclaraciones-questions/{question_id}/status",
    response_model=GenericResponse,
)
async def set_junta_question_status_route(
    session_id: str,
    question_id: str,
    payload: JuntaQuestionStatusRequest,
):
    """HITL: aprueba, excluye o marca enviada una pregunta del listado para la convocante."""
    repo = await get_repository()
    try:
        item = await update_junta_question_status(
            repo,
            session_id,
            question_id,
            status=payload.status,
        )
        session = await repo.get_session(session_id) or {}
        return GenericResponse(
            success=True,
            message="Estado de pregunta actualizado",
            data={
                "question": item.model_dump(mode="json"),
                "junta_aclaraciones_questions": session.get("junta_aclaraciones_questions"),
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(
            "junta_question_status_failed",
            session_id=session_id,
            question_id=question_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Error al actualizar pregunta de junta")
    finally:
        await repo.disconnect()


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
