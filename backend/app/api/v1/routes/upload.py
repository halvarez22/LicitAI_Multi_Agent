from fastapi import APIRouter, File, UploadFile, Depends, Form, HTTPException, Query
from app.services.vector_service import VectorDbServiceClient
from app.services.document_ingestion_router import ALLOWED_EXTENSIONS, DocumentIngestionRouter
from app.api.deps import get_connected_memory
from app.api.schemas.responses import GenericResponse
from app.core.logging_config import get_logger
import asyncio
import shutil
import uuid
import os
import json
import re
from typing import Any, Dict, Optional, TypedDict

logger = get_logger(__name__)

# Registro global de cancelaciones (en un entorno distribuido esto iría a Redis)
cancellation_tokens: Dict[str, bool] = {}


class AutoResolveResult(TypedDict):
    """Contrato de retorno del AutoResolveHook (_sync_pending_after_analysis).

    Attributes:
        resolved_current_pending: True si se resolvió y persistió exitosamente.
        resolved_field: field_key resuelto (None si no se resolvió).
        resolved_value: Valor persistido (None si no se resolvió).
        next_pending_label: Label del siguiente pendiente (None si no hay más).
        next_pending_question: Pregunta del siguiente pendiente (None si no hay más).
        reason: Razón del resultado. Valores posibles:
            "missing_company_id", "no_pending_questions",
            "current_pending_not_profile", "missing_field_key",
            "value_not_found_or_invalid", "persistence_error",
            "timeout", "resolved_and_advanced".
    """

    resolved_current_pending: bool
    resolved_field: Optional[str]
    resolved_value: Optional[str]
    next_pending_label: Optional[str]
    next_pending_question: Optional[str]
    reason: str

router = APIRouter()
# Usamos una ruta relativa para mayor compatibilidad (o absoluta basada en el script)
BASE_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
# In docker envs, we mount data at /data. Fallback to local data dir if not.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join("/data", "uploads") if os.path.exists("/.dockerenv") or os.environ.get("ENVIRONMENT") == "development" else os.path.join(BASE_PATH, "data", "uploads"))
# Fuerza usar /data/uploads si corres under docker, o la variante con env vars. Para asegurar:
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads" if os.environ.get("ENVIRONMENT") == "development" else os.path.join(BASE_PATH, "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _chunk_text_legacy(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """
    Troceo por caracteres (DEPRECADO para Licitaciones).
    Se mantiene solo por compatibilidad con firmas de funciones internas.
    """
    if not text:
        return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += (chunk_size - overlap)
        if start >= text_len or chunk_size <= overlap:
            break
    return chunks


async def _sync_pending_after_analysis(
    memory: Any,
    session_id: str,
    company_id: Optional[str],
    *,
    correlation_id: str = "",
    timeout_seconds: float = 30.0,
) -> AutoResolveResult:
    """Hook post-análisis: intenta cerrar el pendiente activo si el dato puede
    extraerse de las fuentes indexadas con validación estricta.

    No avanza por "éxito técnico de OCR"; solo avanza si el valor extraído pasa
    la validación del campo. Es idempotente: si el pendiente ya fue resuelto,
    retorna ``no_pending_questions`` sin modificar el estado.

    Args:
        memory: Repositorio de persistencia de sesiones y empresas.
        session_id: Identificador de la sesión de licitación.
        company_id: Identificador de la empresa. Si es None o vacío, retorna
            inmediatamente con ``reason="missing_company_id"``.
        correlation_id: ID de correlación para trazabilidad en logs y DataGapAgent.
        timeout_seconds: Tiempo máximo en segundos para la extracción RAG.
            Si se supera, retorna ``reason="timeout"``.

    Returns:
        AutoResolveResult con los campos: resolved_current_pending, resolved_field,
        resolved_value, next_pending_label, next_pending_question, reason.
    """
    out: AutoResolveResult = {
        "resolved_current_pending": False,
        "resolved_field": None,
        "resolved_value": None,
        "next_pending_label": None,
        "next_pending_question": None,
        "reason": "",
    }

    # ── Retorno temprano 1: company_id ausente o vacío ────────────────────────
    if not (company_id or "").strip():
        out["reason"] = "missing_company_id"
        return out

    session_state = await memory.get_session(session_id) or {}
    pending = list(session_state.get("pending_questions") or [])

    # ── Retorno temprano 2: sin pendientes ────────────────────────────────────
    if not pending:
        out["reason"] = "no_pending_questions"
        return out

    idx = max(0, min(int(session_state.get("current_question_index") or 0), len(pending) - 1))
    cur = pending[idx]

    # Rellenar label/question del pendiente activo para todos los retornos tempranos
    # (el endpoint los usa para construir el mensaje del caso 3: "no encontrado")
    out["next_pending_label"] = str(cur.get("label") or "")
    out["next_pending_question"] = str(cur.get("question") or "")

    # ── Retorno temprano 3: tipo no-profile ───────────────────────────────────
    if str(cur.get("type", "profile")) != "profile":
        out["reason"] = "current_pending_not_profile"
        return out

    # ── Retorno temprano 4: field_key vacío ───────────────────────────────────
    field_key = str(cur.get("field") or "").strip()
    if not field_key:
        out["reason"] = "missing_field_key"
        return out

    # ── Extracción RAG con timeout ────────────────────────────────────────────
    from app.agents.mcp_context import MCPContextManager
    from app.agents.data_gap import DataGapAgent

    dg = DataGapAgent(MCPContextManager(memory_repository=memory))
    try:
        extracted = await asyncio.wait_for(
            dg.try_extract_field_from_sources(session_id, company_id, field_key, correlation_id or "post-analysis-sync"),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[AutoResolve] ⏱ Timeout extrayendo '%s' para sesión %s (%.1fs)",
            field_key, session_id, timeout_seconds,
        )
        out["reason"] = "timeout"
        return out

    # ── Validación del valor extraído ─────────────────────────────────────────
    if not extracted or not dg._is_data_valid(field_key, extracted):
        out["reason"] = "value_not_found_or_invalid"
        return out

    # ── Persistencia en master_profile ────────────────────────────────────────
    try:
        company = await memory.get_company(company_id) or {}
        prof = dict(company.get("master_profile") or {})
        prof[field_key] = str(extracted).strip()
        company["master_profile"] = prof
        await memory.save_company(company_id, company)
    except Exception as exc:
        logger.error(
            "[AutoResolve] ❌ Error persistiendo '%s' para sesión %s: %s",
            field_key, session_id, exc,
        )
        out["reason"] = "persistence_error"
        return out

    # ── Avance de cola con lectura atómica fresca ─────────────────────────────
    # Segunda lectura para minimizar ventana de condición de carrera con ChatbotRAGAgent
    fresh_s = await memory.get_session(session_id) or {}
    fresh_pending = list(fresh_s.get("pending_questions") or pending)
    safe_idx = max(0, min(int(fresh_s.get("current_question_index") or idx), max(0, len(fresh_pending) - 1)))

    # Eliminar por posición (idéntico a ChatbotRAGAgent._apply_saved_pending_value)
    new_pending = fresh_pending[:safe_idx] + fresh_pending[safe_idx + 1:]
    if new_pending:
        new_idx = max(0, min(safe_idx, len(new_pending) - 1))
        next_q = new_pending[new_idx]
    else:
        new_idx = 0
        next_q = {}

    fresh_s["pending_questions"] = new_pending
    fresh_s["current_question_index"] = new_idx

    try:
        await memory.save_session(session_id, fresh_s)
    except Exception as exc:
        logger.error(
            "[AutoResolve] ❌ Error guardando session_state para sesión %s: %s",
            session_id, exc,
        )
        out["reason"] = "persistence_error"
        return out

    # ── Log de auditoría ──────────────────────────────────────────────────────
    logger.info(
        "[AutoResolve] ✅ Resuelto '%s' = '%s' para sesión %s",
        field_key, str(extracted)[:40], session_id,
    )

    out.update(
        {
            "resolved_current_pending": True,
            "resolved_field": field_key,
            "resolved_value": str(extracted).strip(),
            "next_pending_label": str(next_q.get("label") or ""),
            "next_pending_question": str(next_q.get("question") or ""),
            "reason": "resolved_and_advanced",
        }
    )
    return out

async def _validate_compliance_after_analysis(
    memory: Any,
    session_id: str,
    doc_id: str,
    company_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Hook estratégico: valida el doc contra los GAPs de cumplimiento."""
    if not company_id:
        return None
        
    from app.agents.mcp_context import MCPContextManager
    from app.agents.validator import RequirementValidatorAgent
    
    validator = RequirementValidatorAgent(MCPContextManager(memory_repository=memory))
    try:
        result = await validator.validate_document_against_gaps(session_id, doc_id, company_id)
        if result.get("success"):
            return result
    except Exception as e:
        logger.error(f"[ValidationHook] Error en validación estratégica: {e}")
    
    return None


@router.post("/cancel/{session_id}", response_model=GenericResponse)
async def cancel_upload(session_id: str):
    """Activa la bandera de cancelación para una sesión específica."""
    cancellation_tokens[session_id] = True
    logger.info(f"[Cancellation] 🛑 Solicitud de abortar carga para sesión: {session_id}")
    return GenericResponse(
        success=True, 
        message="Solicitud de cancelación recibida. Se detendrá el procesamiento del siguiente archivo."
    )

@router.post("/document", response_model=GenericResponse)
@router.post("/upload", response_model=GenericResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """Sube un archivo y lo registra como disponible."""
    # Tarea 4.1 — Validación de extensión antes de guardar en disco (Req 8.1, 8.2, 8.3)
    raw_filename: str = file.filename or ""
    ext: str = raw_filename.lower().rsplit(".", 1)[-1] if "." in raw_filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Tipo de archivo no soportado: .{ext}. "
                f"Extensiones aceptadas: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            ),
        )

    safe_filename = raw_filename.replace(" ", "_").lower()
    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{safe_filename}")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    memory = await get_connected_memory()
    doc_id = str(uuid.uuid4())
    try:
        # 1. Asegurar que la sesión exista sin borrar nombre ni estado (save_session reemplaza el JSON completo)
        prev = await memory.get_session(session_id)
        base = dict(prev) if isinstance(prev, dict) else {}
        base["status"] = "active"
        await memory.save_session(session_id, base)
        
        # 2. Guardar registro inicial
        await memory.save_document(
            doc_id=doc_id,
            session_id=session_id,
            content={"status": "UPLOADED", "file_path": file_path, "filename": raw_filename},
            metadata={"filename": raw_filename, "status": "UPLOADED"}
        )
    except Exception as e:
        print(f"FATAL ERROR UPLOAD: {str(e)}")
        return GenericResponse(
            success=False,
            message=f"Error interno: {str(e)}",
            data=None
        )
    finally:
        await memory.disconnect()

    return GenericResponse(
        success=True,
        message=f"Archivo '{raw_filename}' subido correctamente.",
        data={"doc_id": doc_id, "status": "UPLOADED"}
    )

@router.post("/process/{doc_id}", response_model=GenericResponse)
async def process_document(
    doc_id: str,
    session_id: str = Form(...),
    company_id: Optional[str] = Form(None),
    force: bool = Query(
        False,
        description="Si True, reprocesa aunque esté ANALYZED: borra vectores del doc y vuelve a extraer (Excel→partidas, PDF→OCR).",
    ),
):
    """
    Lanza extracción + indexación de un documento.

    **Camino A (este endpoint):** el cliente llama a procesar un documento ya subido a la sesión
    (feedback inmediato, control de ``force``, chunks PDF típicamente 800 para RAG fino).

    **Camino B:** si solo se dispara ``/agents/process`` con docs aún ``UPLOADED``, el orquestador
    auto-ingesta en background (mismo ``OCRServiceClient`` y mismos chunks PDF 800/200 que aquí).

    Ambos caminos usan el mismo motor PDF/imagen; difieren en *quién dispara* y en parámetros de troceo.
    Con ``force=true`` permite re-ingestar tras cambios de pipeline sin borrar el archivo.
    """
    memory = await get_connected_memory()
    
    doc_data = await memory.get_document(doc_id)
    if not doc_data:
        await memory.disconnect()
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    current_status = doc_data.get("content", {}).get("status")
    if current_status == "ANALYZED" and not force:
        # Para Excel: aunque ya esté ANALYZED, re-ingestar partidas si session_line_items está vacío
        filename_check = doc_data.get("content", {}).get("filename", "")
        if filename_check.lower().endswith((".xlsx", ".xls")):
            from app.services.document_excel_ingest import process_excel_document
            existing = await memory.get_line_items_for_session(session_id)
            if not existing:
                file_path_check = doc_data["content"]["file_path"]
                try:
                    await process_excel_document(memory, session_id, doc_id, file_path_check, filename_check)
                except Exception as e:
                    print(f"WARN: re-ingest Excel line_items failed: {e}")
        elif filename_check.lower().endswith(".docx"):
            from app.services.document_docx_ingest import process_docx_document
            existing = await memory.get_line_items_for_session(session_id)
            if not existing:
                file_path_check = doc_data["content"]["file_path"]
                try:
                    await process_docx_document(memory, session_id, doc_id, file_path_check, filename_check)
                except Exception as e:
                    print(f"WARN: re-ingest DOCX line_items failed: {e}")
        sync = await _sync_pending_after_analysis(memory, session_id, company_id)
        await memory.disconnect()
        filename_check = doc_data.get("content", {}).get("filename", "")
        if sync.get("resolved_current_pending"):
            nxt = sync.get("next_pending_label")
            if nxt:
                msg = (
                    f"He revisado el archivo **{filename_check}** y ya pude extraer **{sync.get('resolved_field')}**. "
                    f"¡Listo! Ahora, para seguir avanzando, necesito: **{nxt}**."
                )
            else:
                msg = (
                    f"He revisado el archivo **{filename_check}** y ya pude extraer **{sync.get('resolved_field')}**. "
                    "¡Listo! Ya no hay pendientes en cola por este bloque."
                )
            return GenericResponse(success=True, message=msg, data={"document": doc_data["content"], "post_analysis_sync": sync})
        if sync.get("reason") == "value_not_found_or_invalid":
            label = str(sync.get("next_pending_label") or "dato pendiente actual")
            msg = (
                f"Reprocesé el archivo **{filename_check}**, pero aún no encuentro **{label}** con claridad. "
                "¿Podrías escribírmelo aquí?"
            )
            return GenericResponse(success=True, message=msg, data={"document": doc_data["content"], "post_analysis_sync": sync})
        return GenericResponse(success=True, message="Documento ya analizado.", data={"document": doc_data["content"], "post_analysis_sync": sync})

    if force:
        try:
            vc = VectorDbServiceClient()
            vc.delete_by_doc_id(session_id, doc_id)
        except Exception as e:
            print(f"WARN process_document force: no se pudieron limpiar vectores previos: {e}")

    file_path = doc_data["content"]["file_path"]
    filename = doc_data["content"]["filename"]
    ext = filename.lower().split(".")[-1]

    # Verificar si se solicitó cancelación antes de empezar
    if cancellation_tokens.get(session_id):
        logger.warning(f"[Cancellation] 🛑 Abortando proceso para {filename} (Sesión cancelada)")
        # Limpiar el token para permitir futuras cargas si el usuario lo desea
        # (Opcional: se podría limpiar en un endpoint específico de 'reset')
        await memory.disconnect()
        return GenericResponse(
            success=False, 
            message="Carga cancelada por el usuario.",
            data={"status": "CANCELLED"}
        )

    # Tarea 4.2 — Routing canónico vía DocumentIngestionRouter (Req 2.1, 2.2, 2.3)
    router_instance = DocumentIngestionRouter()
    try:
        ocr_result = await router_instance.ingest(
            file_path=file_path,
            filename=filename,
            session_id=session_id,
            doc_id=doc_id,
            memory=memory,
        )
    except Exception as e:
        await memory.disconnect()
        raise HTTPException(status_code=500, detail=f"Error procesando documento: {str(e)}")

    if not ocr_result.get("success", False) or "error" in ocr_result:
        await memory.disconnect()
        error_detail = ocr_result.get('error', 'Fallo desconocido en la cadena de Extracción.')
        raise HTTPException(status_code=502, detail=f"Fallo en Extracción: {error_detail}")

    raw_text = ocr_result.get("extracted_text", "").strip()
    
    # --- GUARDA DE SEGURIDAD (HARDENING) ---
    # Validar que la extracción sea significativa para PDFs e Imágenes
    if ext not in ["xlsx", "xls", "csv"] and len(raw_text) < 100:
        await memory.disconnect()
        raise HTTPException(
            status_code=502, 
            detail="Extracción Insuficiente: El documento no contiene suficiente texto legible (<100 chars)."
        )

    pages = ocr_result.get("pages", [])

    from app.services.document_vector_index import index_pages_atomic

    vector_client = VectorDbServiceClient()
    indexed = index_pages_atomic(session_id, doc_id, filename, pages, vector_client)
    logger.info(
        "ingestion_pages_indexed",
        session_id=session_id,
        filename=filename[:80],
        chunks=indexed,
    )

    # Actualizar Estado en DB
    updated_content = doc_data["content"]
    updated_content["status"] = "ANALYZED"
    updated_content["total_pages"] = ocr_result.get("total_pages", 1)
    updated_content["extracted_text"] = raw_text # Persistir el texto completo para los agentes
    
    await memory.save_document(doc_id, session_id, updated_content, {"status": "ANALYZED", "filename": filename})

    # ── AutoResolveHook: intentar resolver pendiente activo desde el doc recién indexado ──
    try:
        sync = await _sync_pending_after_analysis(
            memory, session_id, company_id,
            correlation_id=doc_id,
        )
    except Exception as exc:
        logger.warning(
            "[AutoResolve] ⚠️ Excepción no controlada en hook para sesión %s: %s",
            session_id, exc, exc_info=True,
        )
        sync = AutoResolveResult(
            resolved_current_pending=False,
            resolved_field=None,
            resolved_value=None,
            next_pending_label=None,
            next_pending_question=None,
            reason="hook_exception",
        )

    # ── ValidationHook: Validar estratégicamente contra GAPs ──────────────────
    validation_res = await _validate_compliance_after_analysis(memory, session_id, doc_id, company_id)

    await memory.disconnect()

    # ── Caso 1: Resuelto con siguiente pendiente ──────────────────────────────
    if sync.get("resolved_current_pending"):
        nxt = sync.get("next_pending_label")
        if nxt:
            msg = (
                f"He revisado el archivo **{filename}** y ya pude extraer **{sync.get('resolved_field')}**. "
                f"¡Listo! Ahora, para seguir avanzando, necesito: **{nxt}**."
            )
        else:
            # ── Caso 2: Resuelto sin más pendientes ───────────────────────────
            msg = (
                f"He revisado el archivo **{filename}** y ya pude extraer **{sync.get('resolved_field')}**. "
                "¡Listo! Ya no hay pendientes en cola por este bloque."
            )
        return GenericResponse(success=True, message=msg, data={"post_analysis_sync": sync})

    # ── Caso 3: No encontrado — invitar a escribirlo por chat ─────────────────
    if sync.get("reason") == "value_not_found_or_invalid":
        label = str(sync.get("next_pending_label") or "dato pendiente actual")
        msg = (
            f"Reprocesé el archivo **{filename}**, pero aún no encuentro **{label}** con claridad. "
            "¿Podrías escribírmelo aquí?"
        )
        return GenericResponse(success=True, message=msg, data={"post_analysis_sync": sync})

    # ── Caso 3.5: Validación estratégica exitosa ──────────────────────────────
    if validation_res:
        return GenericResponse(
            success=True, 
            message=validation_res["message"], 
            data={"post_analysis_sync": sync, "strategic_validation": validation_res}
        )

    # ── Caso 4: Sin pendientes o sin company_id — confirmación estándar ───────
    return GenericResponse(
        success=True,
        message=f"Documento '{filename}' analizado con éxito.",
        data={"post_analysis_sync": sync},
    )

@router.get("/list/{session_id}", response_model=GenericResponse)
async def list_documents(session_id: str):
    """Lista todos los documentos asociados a una sesión."""
    memory = await get_connected_memory()
    
    try:
        docs = await memory.get_documents(session_id)
        formatted_docs = []
        for d in docs:
            formatted_docs.append({
                "id": d["id"],
                "name": d["content"].get("filename", "Sin nombre"),
                "status": d["content"].get("status", "UPLOADED")
            })
        
        return GenericResponse(
            success=True, 
            message=f"Se encontraron {len(docs)} documentos.",
            data={"documents": formatted_docs}
        )
    finally:
        await memory.disconnect()


@router.get("/line-items/{session_id}", response_model=GenericResponse)
async def list_session_line_items(session_id: str):
    """
    Lista partidas económicas persistidas (Excel → session_line_items) para la sesión.
    Útil para verificar ingesta desde la API sin acceder a Postgres a mano.
    """
    memory = await get_connected_memory()
    try:
        rows = await memory.get_line_items_for_session(session_id)
        return GenericResponse(
            success=True,
            message=f"{len(rows)} partida(s) tabular(es) en la sesión.",
            data={"count": len(rows), "items": rows},
        )
    finally:
        await memory.disconnect()


@router.get("/economic-normalized/{session_id}", response_model=GenericResponse)
async def get_economic_normalized(session_id: str):
    """
    Devuelve el payload canónico `economic_normalized_data` de la sesión (Sprint 1).
    """
    memory = await get_connected_memory()
    try:
        session = await memory.get_session(session_id) or {}
        data = session.get("economic_normalized_data") or {}
        return GenericResponse(
            success=True,
            message="economic_normalized_data recuperado.",
            data={"economic_normalized_data": data},
        )
    finally:
        await memory.disconnect()


@router.delete("/{doc_id}", response_model=GenericResponse)
async def delete_document(doc_id: str, session_id: str = Form(...)):
    """Elimina una fuente del sistema (Archivo, DB y Vectores)."""
    memory = await get_connected_memory()
    
    doc_data = await memory.get_document(doc_id)
    if not doc_data:
        await memory.disconnect()
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # 1. Borrar archivo físico
    file_path = doc_data["content"].get("file_path")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"WARN: No se pudo eliminar el archivo {file_path}: {e}")

    # 2. Borrar de ChromaDB
    try:
        vector_client = VectorDbServiceClient()
        vector_client.delete_by_doc_id(session_id, doc_id)
    except Exception as e:
        print(f"WARN: Fallo al borrar vectores: {e}")

    # 3. Borrar de la DB relacional (Memory)
    try:
        await memory.delete_document(doc_id)
        
        # --- LIMPIEZA AUTOMÁTICA DE DICTAMEN ---
        # Si borramos el archivo, el dictamen basado en él ya no es válido.
        session_data = await memory.get_session(session_id)
        if session_data and "dictamen" in session_data:
            session_data["dictamen"] = None
            await memory.save_session(session_id, session_data)
            print(f"DEBUG: Dictamen reseteado para sesión={session_id} tras borrado de doc_id={doc_id}")
            
    except Exception as e:
        print(f"WARN: Fallo al borrar de DB o resetear dictamen: {e}")
    
    await memory.disconnect()
    return GenericResponse(success=True, message=f"Fuente '{doc_data['content'].get('filename')}' eliminada correctamente.")


@router.post("/ingest-economic-excel", response_model=GenericResponse)
async def ingest_economic_excel(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    company_id: str = Form(...)
):
    """
    Recibe un archivo Excel estructurado con precios y variables de nómina,
    los procesa e inyecta directamente en la base de datos (Master Profile y Session State).
    """
    raw_filename = file.filename or ""
    ext = raw_filename.lower().rsplit(".", 1)[-1] if "." in raw_filename else ""
    if ext not in ("xlsx", "xls"):
        raise HTTPException(
            status_code=415,
            detail=f"Formato no soportado: .{ext}. Debe ser un archivo Excel estructurado (.xlsx o .xls)."
        )

    # Guardar archivo temporal
    safe_filename = raw_filename.replace(" ", "_").lower()
    temp_path = os.path.join(UPLOAD_DIR, f"temp_economic_{uuid.uuid4()}_{safe_filename}")
    
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    memory = await get_connected_memory()
    try:
        from app.services.economic_data_ingestor import EconomicDataIngestor
        res = await EconomicDataIngestor.ingest_and_save_data(
            memory=memory,
            session_id=session_id,
            company_id=company_id,
            file_path=temp_path
        )
        
        # Eliminar archivo temporal
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if not res["success"]:
            raise HTTPException(status_code=400, detail=res["message"])
            
        return GenericResponse(
            success=True,
            message=res["message"],
            data=res.get("data")
        )
    finally:
        await memory.disconnect()

