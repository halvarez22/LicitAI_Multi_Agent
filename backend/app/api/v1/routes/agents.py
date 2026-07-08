from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.api.schemas.requests import ProcessBasesRequest
from app.api.schemas.responses import GenericResponse, AgentExecutionResponse
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.api.deps import get_connected_memory
from app.core.logging_config import get_logger
import asyncio
import logging

logger = get_logger("licitai.agents")
router = APIRouter()

from app.services.vector_service import VectorDbServiceClient
from app.services.document_ingestion_router import DocumentIngestionRouter
import uuid
from datetime import datetime, timezone
import json
from app.config.settings import settings
from typing import Any, Dict
from app.services.job_service import (
    update_job_status,
    redis_client,
    link_session_job,
    clear_session_job,
    get_active_session_job,
)
from app.utils.pipeline_telemetry import build_pipeline_telemetry

def _job_completion_message(final_status: str) -> str:
    """Devuelve mensaje de cierre alineado al estado final del orquestador."""
    if final_status == "go_no_go_pending":
        return "Pipeline en pausa: pendiente autorización Go/No-Go."
    if final_status == "waiting_for_data":
        return "Pipeline en pausa: faltan datos para continuar."
    if final_status == "partial":
        return "Pipeline completado con advertencias."
    if final_status == "error":
        return "Pipeline finalizado con incidencias."
    return "Análisis finalizado con éxito."


def _job_completion_progress(final_status: str) -> dict:
    """
    Progreso final del job Redis alineado al estado del orquestador (PR2).

    Evita ``pct: 100`` cuando el pipeline quedó en pausa (``waiting_for_data``).
    """
    held_statuses = frozenset({"waiting_for_data", "go_no_go_pending"})
    if final_status in held_statuses:
        return {
            "stage": "held",
            "pct": 72,
            "message": _job_completion_message(final_status),
            "orchestrator_held": True,
            "orchestrator_status": final_status,
        }
    if final_status == "error":
        return {
            "stage": "done",
            "pct": 0,
            "message": _job_completion_message(final_status),
            "orchestrator_held": False,
            "orchestrator_status": final_status,
        }
    if final_status == "partial":
        return {
            "stage": "done",
            "pct": 100,
            "message": _job_completion_message(final_status),
            "orchestrator_held": False,
            "orchestrator_status": final_status,
        }
    return {
        "stage": "done",
        "pct": 100,
        "message": _job_completion_message(final_status),
        "orchestrator_held": False,
        "orchestrator_status": final_status,
    }

def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]

@router.post("/process", response_model=GenericResponse, status_code=202)
async def process_licitation_bases(request: ProcessBasesRequest, background_tasks: BackgroundTasks):
    """
    Desencadena el análisis multi-agente de forma ASÍNCRONA.
    Retorna un job_id para seguimiento.
    """
    memory = await get_connected_memory()
    
    try:
        # Validar existencia de documentos
        docs = await memory.get_documents(request.session_id)
        if not docs:
            raise HTTPException(status_code=404, detail="No se encontraron documentos para esta sesión")

        # Crear Job ID (limpia vínculo con job anterior de la sesión)
        job_id = str(uuid.uuid4())
        clear_session_job(request.session_id)
        
        # Inicializar estado en Redis
        update_job_status(
            job_id=job_id,
            status="QUEUED",
            progress={"stage": "init", "pct": 0, "message": "Encolando tarea de análisis"}
        )
        link_session_job(request.session_id, job_id)

        # Encolar tarea en background (thread dedicado: no bloquear API HTTP durante Compliance)
        background_tasks.add_task(
            _run_orchestrator_job_isolated,
            job_id,
            request,
        )

        return GenericResponse(
            success=True,
            message=f"Análisis iniciado. Job ID: {job_id}",
            data={"job_id": job_id, "session_id": request.session_id}
        )

    except Exception as e:
        logger.error(f"Error al encolar proceso: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await memory.disconnect()

async def _run_orchestrator_job_isolated(job_id: str, request: ProcessBasesRequest) -> None:
    """
    Ejecuta el pipeline en un thread con event loop propio.

    Evita que Compliance/Ollama monopolice el loop de Uvicorn y deje colgados
    endpoints ligeros (listado de fuentes, estado de job, etc.).

    Usa un adaptador Postgres dedicado al thread; nunca toca el singleton del
    event loop principal (evita "Future attached to a different loop").
    """

    def _thread_main() -> None:
        import os

        from app.config.settings import settings
        from app.memory.adapters.postgres_adapter import PostgresMemoryAdapter

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        adapter = PostgresMemoryAdapter(
            connection_string=settings.DATABASE_URL or os.getenv("DATABASE_URL"),
            encryption_key=os.getenv("MEMORY_ENCRYPTION_KEY"),
        )
        try:

            async def _bootstrap_and_run() -> None:
                from app.memory.runtime import reset_memory_override, set_memory_override

                if not await adapter.connect():
                    raise RuntimeError("PostgreSQL no disponible para job aislado")
                token = set_memory_override(adapter)
                try:
                    await _run_orchestrator_job(job_id, request, memory=adapter)
                finally:
                    reset_memory_override(token)

            loop.run_until_complete(_bootstrap_and_run())
        finally:
            try:
                if getattr(adapter, "engine", None):
                    loop.run_until_complete(adapter.engine.dispose())
            except Exception:
                pass
            loop.close()

    await asyncio.to_thread(_thread_main)


async def _run_orchestrator_job(
    job_id: str,
    request: ProcessBasesRequest,
    memory=None,
):
    """Tarea de fondo que ejecuta el pipeline real."""
    thread_local_memory = memory is not None
    if memory is None:
        memory = await get_connected_memory()
    
    try:
        update_job_status(job_id, "RUNNING", {"stage": "ingestion", "pct": 10, "message": "Iniciando ingesta de documentos"})
        
        # ── PASO PREVIO: AUTO-INGESTA (Camino B) ─────────────────────────────────
        # Documentos UPLOADED sin pasar por POST /upload/process/{doc_id}: usa el
        # DocumentIngestionRouter canónico — mismo comportamiento que el Camino A.
        docs = await memory.get_documents(request.session_id)
        vector_client = VectorDbServiceClient()
        col = vector_client.get_or_create_collection(request.session_id)
        is_rag_empty = col.count() == 0
        
        _router = DocumentIngestionRouter()

        for d in docs:
            content = d.get("content", {})
            # Si el RAG está vacío, ignoramos el status y re-ingestamos forzosamente.
            if content.get("status") != "UPLOADED" and not is_rag_empty:
                continue

            filename = content.get("filename") or ""
            file_path = content.get("file_path")
            ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

            update_job_status(
                job_id,
                "RUNNING",
                {"stage": "ingestion", "pct": 15, "message": f"Procesando: {filename}"},
            )

            ocr_ctx = await _router.ingest(
                file_path=file_path,
                filename=filename,
                session_id=request.session_id,
                doc_id=d["id"],
                memory=memory,
            )

            if not ocr_ctx.get("success"):
                logger.error(
                    "background_ingestion_failed",
                    doc_id=d["id"],
                    session_id=request.session_id,
                    error=ocr_ctx.get("error", "unknown"),
                )
                content["status"] = "ERROR"
                await memory.save_document(
                    d["id"], request.session_id, content, {"status": "ERROR"}
                )
                continue

            raw_text = ocr_ctx.get("extracted_text", "")
            pages = ocr_ctx.get("pages", [])
            from app.services.document_vector_index import index_pages_atomic

            index_pages_atomic(
                request.session_id,
                d["id"],
                filename,
                pages,
                vector_client,
            )

            content["status"] = "ANALYZED"
            content["extracted_text"] = raw_text
            content["total_pages"] = ocr_ctx.get("total_pages", len(pages))
            await memory.save_document(
                d["id"], request.session_id, content, {"status": "ANALYZED"}
            )
            try:
                from app.services.document_catalog_service import (
                    classify_and_persist_catalog_entry,
                )

                await classify_and_persist_catalog_entry(
                    memory, request.session_id, d["id"], content
                )
            except Exception as catalog_exc:
                logger.warning(
                    "background_document_catalog_failed session=%s doc=%s err=%s",
                    request.session_id,
                    d["id"],
                    catalog_exc,
                )

        # ── PASO 2: EJECUCIÓN DEL ORQUESTADOR ────────────────────────────────────
        update_job_status(job_id, "RUNNING", {"stage": "orchestration", "pct": 30, "message": "Iniciando orquestación de agentes"})
        
        mcp_manager = MCPContextManager(memory_repository=memory)
        orchestrator = OrchestratorAgent(context_manager=mcp_manager)

        generation_mode = request.generation_mode or (request.company_data or {}).get("generation_mode")
        generation_stream = request.generation_stream or (request.company_data or {}).get("generation_stream")
        
        resultado = await orchestrator.process(
            session_id=request.session_id,
            input_data={
                "company_id": request.company_id,
                "company_data": request.company_data,
                "resume_generation": request.resume_generation,
                "generation_mode": generation_mode,
                "generation_stream": generation_stream,
                "job_id": job_id
            }
        )

        resultado_dict = resultado if isinstance(resultado, dict) else {}
        pipeline_telemetry = build_pipeline_telemetry(resultado_dict)
        persisted_dictamen = None

        # Formatear el resultado final similar a AgentExecutionResponse
        final_data = {
            "status": resultado_dict.get("status", "error"),
            "session_id": request.session_id,
            "chatbot_message": resultado_dict.get("chatbot_message")
            or resultado_dict.get("message"),
            "agent_decision": resultado_dict.get("orchestrator_decision"),
            "go_no_go_result": resultado_dict.get("go_no_go_result"),
            "data": resultado_dict.get("results"),
            "auto_filled": resultado_dict.get("auto_filled"),
            "missing_fields": resultado_dict.get("missing_fields"),
            "generation_state": resultado_dict.get("generation_state"),
            "fast_track_document_candidates": resultado_dict.get("fast_track_document_candidates"),
            "metadata": resultado_dict.get("metadata"),
            "pipelineTelemetry": pipeline_telemetry,
        }

        # --- AUTO-PERSISTENCIA DEL DICTAMEN (INDUSTRIALIZACIÓN) ---
        # Incluye waiting_for_data, error y go_no_go_pending para conservar telemetría.
        persist_statuses = ("success", "partial", "waiting_for_data", "error", "go_no_go_pending")
        if resultado_dict.get("status") in persist_statuses:
            try:
                from app.utils.audit_processor import process_audit_results_backend

                line_items_count: int | None = None
                try:
                    rows = await memory.get_line_items_for_session(request.session_id)
                    line_items_count = len(rows or [])
                except Exception as li_exc:
                    logger.warning(
                        "dictamen_line_items_count_skip session=%s err=%s",
                        request.session_id,
                        li_exc,
                    )

                session_for_ccc = await memory.get_session(request.session_id) or {}
                ccc_raw = (
                    resultado_dict.get("document_candidates_consolidated")
                    or session_for_ccc.get("document_candidates_consolidated")
                )
                extraction_health = None
                try:
                    from app.services.extraction_health_service import (
                        compute_extraction_health_for_session,
                    )

                    extraction_health = await compute_extraction_health_for_session(
                        memory, request.session_id
                    )
                except Exception as ext_exc:
                    logger.warning(
                        "dictamen_extraction_health_skip session=%s err=%s",
                        request.session_id,
                        ext_exc,
                    )

                dictamen = process_audit_results_backend(
                    {
                        "status": resultado_dict.get("status"),
                        "analysis": resultado_dict.get("results", {}).get("analysis", {}),
                        "compliance": resultado_dict.get("results", {}).get("compliance", {}),
                        "economic": resultado_dict.get("results", {}).get("economic", {}),
                        "error": resultado_dict.get("message", "") or "",
                        "orchestrator_decision": resultado_dict.get("orchestrator_decision"),
                        "fast_track_document_candidates": resultado_dict.get("fast_track_document_candidates") or resultado_dict.get("fastTrackDocumentCandidates"),
                        "document_candidates_consolidated": ccc_raw,
                    },
                    pipeline_telemetry=pipeline_telemetry,
                    line_items_count=line_items_count,
                    session_state=session_for_ccc,
                    extraction_health=extraction_health,
                )

                if dictamen:
                    persisted_dictamen = dictamen
                    session_data = await memory.get_session(request.session_id) or {}
                    session_data["dictamen"] = dictamen
                    if dictamen.get("dictamen_curated_v1"):
                        session_data["dictamen_curated_v1"] = dictamen["dictamen_curated_v1"]
                    ccc_saved = dictamen.get("documentCandidatesConsolidated")
                    if isinstance(ccc_saved, dict) and ccc_saved.get("sobre_1_tecnico") is not None:
                        session_data["document_candidates_consolidated"] = ccc_saved
                    await memory.save_session(request.session_id, session_data)
                    logger.info(
                        f"Dictamen auto-persistido sesión={request.session_id} "
                        f"status_orquestador={resultado_dict.get('status')}"
                    )
            except Exception as e:
                logger.error(f"Error en auto-persistencia del dictamen: {e}")

        if persisted_dictamen:
            final_data["dictamen"] = persisted_dictamen
        
        final_status = str(resultado_dict.get("status", "error"))
        update_job_status(
            job_id,
            "COMPLETED",
            _job_completion_progress(final_status),
            result=final_data,
        )
        logger.info(f"Job {job_id} completado con éxito")

    except Exception as e:
        logger.error(f"Error en Job {job_id}: {e}")
        # Recuperar progreso actual para el rastro forense
        job_raw = redis_client.get(f"job:{job_id}")
        last_progress = json.loads(job_raw).get("progress", {}) if job_raw else {}
        
        update_job_status(
            job_id=job_id,
            status="FAILED",
            progress={
                "stage": "error",
                "message": (str(e) or "Error en el análisis")[:400],
                "pct": last_progress.get("pct", 0),
            },
            error=str(e),
            forensic_traceback={
                "last_stage": last_progress.get("stage", "unknown"),
                "last_zone": last_progress.get("zone", "none"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    finally:
        try:
            from app.services.generation_concurrency_controller import (
                dual_stream_enabled,
                release_stream_lock,
                resolve_generation_stream_from_input,
            )
            from app.services.generation_mode_policy import resolve_generation_mode_from_input
            from app.services.generation_queue_controller import sync_flat_jobs_from_streams

            if dual_stream_enabled() and job_id and memory is not None:
                session_data = await memory.get_session(request.session_id) or {}
                gen_state = session_data.get("generation_state")
                if isinstance(gen_state, dict):
                    gmode = resolve_generation_mode_from_input(
                        {
                            "generation_mode": request.generation_mode,
                            "company_data": request.company_data,
                        },
                        session_data,
                    )
                    stream_id = resolve_generation_stream_from_input(
                        {
                            "generation_stream": request.generation_stream,
                            "company_data": request.company_data,
                        },
                        gmode,
                    )
                    if stream_id in ("technical", "economic"):
                        release_stream_lock(gen_state, stream_id, job_id)
                        sync_flat_jobs_from_streams(gen_state)
                        await memory.save_session(
                            request.session_id,
                            {"generation_state": gen_state},
                        )
        except Exception as rel_exc:
            logger.warning(
                "dual_stream_lock_release_failed session=%s job=%s err=%s",
                request.session_id,
                job_id,
                rel_exc,
            )
        clear_session_job(request.session_id)
        if thread_local_memory:
            if getattr(memory, "engine", None):
                await memory.engine.dispose()
        else:
            await memory.disconnect()

@router.get("/sessions/{session_id}/active-job", response_model=GenericResponse)
async def get_session_active_job(session_id: str):
    """
    Job de análisis en curso para la sesión (si existe en Redis).
    Permite al frontend reanudar la ventana de progreso tras recargar la página.
    """
    job = get_active_session_job(session_id)
    if not job:
        return GenericResponse(success=True, message="Sin job activo", data=None)
    return GenericResponse(success=True, message="Job activo", data=job)


@router.get("/jobs/{job_id}/status", response_model=GenericResponse)
async def get_job_status_endpoint(job_id: str):
    """
    Retorna el estado de progreso del análisis asíncrono.
    Jobs RUNNING/QUEUED sin heartbeat reciente se reconcilian como FAILED.
    """
    from app.services.job_service import get_job_status as fetch_job_status

    job_data = fetch_job_status(job_id, reconcile_stale=False)
    if not job_data:
        raise HTTPException(status_code=404, detail="ID de Job no encontrado")

    return GenericResponse(
        success=True,
        message=f"Estado del job: {job_data.get('status')}",
        data=job_data,
    )
