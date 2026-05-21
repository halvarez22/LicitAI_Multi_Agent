from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.api.schemas.requests import ProcessBasesRequest
from app.api.schemas.responses import GenericResponse, AgentExecutionResponse
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.api.deps import get_connected_memory
from app.core.logging_config import get_logger
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
from app.services.job_service import update_job_status, redis_client
from app.utils.pipeline_telemetry import build_pipeline_telemetry

def _job_completion_message(final_status: str) -> str:
    """Devuelve mensaje de cierre alineado al estado final del orquestador."""
    if final_status == "go_no_go_pending":
        return "Pipeline en pausa: pendiente autorización Go/No-Go."
    if final_status == "waiting_for_data":
        return "Pipeline en pausa: faltan datos para continuar."
    if final_status == "error":
        return "Pipeline finalizado con incidencias."
    return "Análisis finalizado con éxito."

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

        # Crear Job ID
        job_id = str(uuid.uuid4())
        
        # Inicializar estado en Redis
        update_job_status(
            job_id=job_id,
            status="QUEUED",
            progress={"stage": "init", "pct": 0, "message": "Encolando tarea de análisis"}
        )

        # Encolar tarea en background
        background_tasks.add_task(
            _run_orchestrator_job,
            job_id,
            request
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

async def _run_orchestrator_job(job_id: str, request: ProcessBasesRequest):
    """Tarea de fondo que ejecuta el pipeline real."""
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
            # Chunk size mayor para tabulares (Excel/CSV/DOCX) que para PDFs/texto
            chunk_size = 4000 if ext in ("xlsx", "xls", "csv", "docx") else 800
            for page in pages:
                p_text = page.get("text", "")
                if p_text:
                    chunks = _chunk_text(p_text, chunk_size=chunk_size, overlap=200)
                    metadatas = [
                        {
                            "source": filename,
                            "session_id": request.session_id,
                            "page": page.get("page"),
                            "doc_id": d["id"],
                        }
                        for _ in chunks
                    ]
                    vector_client.add_texts(request.session_id, chunks, metadatas)

            content["status"] = "ANALYZED"
            content["extracted_text"] = raw_text
            content["total_pages"] = ocr_ctx.get("total_pages", len(pages))
            await memory.save_document(
                d["id"], request.session_id, content, {"status": "ANALYZED"}
            )

        # ── PASO 2: EJECUCIÓN DEL ORQUESTADOR ────────────────────────────────────
        update_job_status(job_id, "RUNNING", {"stage": "orchestration", "pct": 30, "message": "Iniciando orquestación de agentes"})
        
        mcp_manager = MCPContextManager(memory_repository=memory)
        orchestrator = OrchestratorAgent(context_manager=mcp_manager)
        
        resultado = await orchestrator.process(
            session_id=request.session_id,
            input_data={
                "company_id": request.company_id,
                "company_data": request.company_data,
                "resume_generation": request.resume_generation,
                "job_id": job_id
            }
        )

        resultado_dict = resultado if isinstance(resultado, dict) else {}
        pipeline_telemetry = build_pipeline_telemetry(resultado_dict)

        # Formatear el resultado final similar a AgentExecutionResponse
        final_data = {
            "status": resultado_dict.get("status", "error"),
            "session_id": request.session_id,
            "chatbot_message": resultado_dict.get("chatbot_message"),
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

                session_for_ccc = await memory.get_session(request.session_id) or {}
                ccc_raw = (
                    resultado_dict.get("document_candidates_consolidated")
                    or session_for_ccc.get("document_candidates_consolidated")
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
                )

                if dictamen:
                    session_data = await memory.get_session(request.session_id) or {}
                    session_data["dictamen"] = dictamen
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
        
        final_status = str(resultado_dict.get("status", "error"))
        update_job_status(
            job_id,
            "COMPLETED",
            {
                "stage": "done",
                "pct": 100,
                "message": _job_completion_message(final_status),
            },
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
        if 'orchestrator' in locals():
            await orchestrator.context_manager.memory.disconnect()
        else:
            await memory.disconnect()

@router.get("/jobs/{job_id}/status", response_model=GenericResponse)
async def get_job_status(job_id: str):
    """
    Retorna el estado de progreso del análisis asíncrono.
    """
    job_data_raw = redis_client.get(f"job:{job_id}")
    if not job_data_raw:
        raise HTTPException(status_code=404, detail="ID de Job no encontrado")
        
    job_data = json.loads(job_data_raw)
    return GenericResponse(
        success=True,
        message=f"Estado del job: {job_data.get('status')}",
        data=job_data
    )
