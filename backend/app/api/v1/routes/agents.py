from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.api.schemas.requests import ProcessBasesRequest
from app.api.schemas.responses import GenericResponse, AgentExecutionResponse
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.memory.factory import MemoryAdapterFactory
from app.core.logging_config import get_logger
import logging

logger = get_logger("licitai.agents")
router = APIRouter()

from app.services.ocr_service import OCRServiceClient
from app.services.vector_service import VectorDbServiceClient
import uuid
from datetime import datetime, timezone
import json
from app.config.settings import settings
from typing import Any, Dict
from app.services.job_service import update_job_status, redis_client
from app.utils.pipeline_telemetry import build_pipeline_telemetry

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
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
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
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    try:
        update_job_status(job_id, "RUNNING", {"stage": "ingestion", "pct": 10, "message": "Iniciando ingesta de documentos"})
        
        # ── PASO PREVIO: AUTO-INGESTA ───────────────────────────────────────────
        docs = await memory.get_documents(request.session_id)
        ocr_client = OCRServiceClient()
        vector_client = VectorDbServiceClient()
        
        for d in docs:
            content = d.get("content", {})
            if content.get("status") == "UPLOADED":
                filename = content.get("filename") or ""
                file_path = content.get("file_path")
                ext = filename.lower().split(".")[-1] if filename else ""

                if ext in ("xlsx", "xls"):
                    update_job_status(
                        job_id,
                        "RUNNING",
                        {"stage": "ingestion", "pct": 15, "message": f"Procesando Excel: {filename}"},
                    )
                    try:
                        from app.services.document_excel_ingest import process_excel_document

                        ocr_ctx, _rows = await process_excel_document(
                            memory, request.session_id, d["id"], file_path, filename
                        )
                    except Exception as e:
                        logger.error(f"Ingesta Excel fallida doc={d['id']}: {e}")
                        content["status"] = "FAILED_EXTRACTION"
                        await memory.save_document(
                            d["id"], request.session_id, content, {"status": "FAILED_EXTRACTION"}
                        )
                        continue

                    raw_text = ocr_ctx.get("extracted_text", "")
                    pages = ocr_ctx.get("pages", [])
                    is_valid = ocr_ctx.get("success") is True and (
                        len(raw_text.strip()) >= 20 or len(pages) > 0
                    )
                    if not is_valid:
                        content["status"] = "FAILED_EXTRACTION"
                        await memory.save_document(
                            d["id"], request.session_id, content, {"status": "FAILED_EXTRACTION"}
                        )
                        continue

                    chunk_size = 4000
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
                    continue

                update_job_status(job_id, "RUNNING", {"stage": "ingestion", "pct": 15, "message": f"Procesando OCR: {filename}"})

                ocr_ctx = await ocr_client.scan_document(file_path)
                raw_text = ocr_ctx.get("extracted_text", "")

                is_valid = ("error" not in ocr_ctx and ocr_ctx.get("success") is True and len(raw_text.strip()) >= 100)

                if not is_valid:
                    content["status"] = "FAILED_EXTRACTION"
                    await memory.save_document(d["id"], request.session_id, content, {"status": "FAILED_EXTRACTION"})
                    continue

                pages = ocr_ctx.get("pages", [])
                for page in pages:
                    p_text = page.get("text", "")
                    if p_text:
                        chunks = _chunk_text(p_text)
                        metadatas = [{"source": filename, "session_id": request.session_id, "page": page.get("page"), "doc_id": d["id"]} for _ in chunks]
                        vector_client.add_texts(request.session_id, chunks, metadatas)

                content["status"] = "ANALYZED"
                content["extracted_text"] = raw_text
                content["total_pages"] = ocr_ctx.get("total_pages", len(pages))
                await memory.save_document(d["id"], request.session_id, content, {"status": "ANALYZED"})

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
            "data": resultado_dict.get("results"),
            "auto_filled": resultado_dict.get("auto_filled"),
            "missing_fields": resultado_dict.get("missing_fields"),
            "generation_state": resultado_dict.get("generation_state"),
            "metadata": resultado_dict.get("metadata"),
            "pipelineTelemetry": pipeline_telemetry,
        }

        # --- AUTO-PERSISTENCIA DEL DICTAMEN (INDUSTRIALIZACIÓN) ---
        # Incluye waiting_for_data y error para que F5 conserve telemetría y hallazgos parciales.
        persist_statuses = ("success", "partial", "waiting_for_data", "error")
        if resultado_dict.get("status") in persist_statuses:
            try:
                from app.utils.audit_processor import process_audit_results_backend

                dictamen = process_audit_results_backend(
                    {
                        "status": resultado_dict.get("status"),
                        "analysis": resultado_dict.get("results", {}).get("analysis", {}),
                        "compliance": resultado_dict.get("results", {}).get("compliance", {}),
                        "economic": resultado_dict.get("results", {}).get("economic", {}),
                        "error": resultado_dict.get("message", "") or "",
                        "orchestrator_decision": resultado_dict.get("orchestrator_decision"),
                    },
                    pipeline_telemetry=pipeline_telemetry,
                )

                if dictamen:
                    session_data = await memory.get_session(request.session_id) or {}
                    session_data["dictamen"] = dictamen
                    await memory.save_session(request.session_id, session_data)
                    logger.info(
                        f"Dictamen auto-persistido sesión={request.session_id} "
                        f"status_orquestador={resultado_dict.get('status')}"
                    )
            except Exception as e:
                logger.error(f"Error en auto-persistencia del dictamen: {e}")
        
        update_job_status(job_id, "COMPLETED", {"stage": "done", "pct": 100, "message": "Análisis finalizado con éxito"}, result=final_data)
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
