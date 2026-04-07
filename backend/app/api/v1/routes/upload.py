from fastapi import APIRouter, File, UploadFile, Depends, Form, HTTPException, Query
from app.services.ocr_service import OCRServiceClient
from app.services.vector_service import VectorDbServiceClient
from app.memory.factory import MemoryAdapterFactory
from app.api.schemas.responses import GenericResponse
import shutil
import uuid
import os
import json

router = APIRouter()
# Usamos una ruta relativa para mayor compatibilidad (o absoluta basada en el script)
BASE_PATH = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
# In docker envs, we mount data at /data. Fallback to local data dir if not.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join("/data", "uploads") if os.path.exists("/.dockerenv") or os.environ.get("ENVIRONMENT") == "development" else os.path.join(BASE_PATH, "data", "uploads"))
# Fuerza usar /data/uploads si corres under docker, o la variante con env vars. Para asegurar:
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/data/uploads" if os.environ.get("ENVIRONMENT") == "development" else os.path.join(BASE_PATH, "data", "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return [c for c in chunks if c.strip()]

@router.post("/document", response_model=GenericResponse)
@router.post("/upload", response_model=GenericResponse)
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Form(...)
):
    """Sube un archivo y lo registra como disponible."""
    safe_filename = file.filename.replace(" ", "_").lower()
    file_path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{safe_filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
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
            content={"status": "UPLOADED", "file_path": file_path, "filename": file.filename},
            metadata={"filename": file.filename, "status": "UPLOADED"}
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
        message=f"Archivo '{file.filename}' subido correctamente.",
        data={"doc_id": doc_id, "status": "UPLOADED"}
    )

@router.post("/process/{doc_id}", response_model=GenericResponse)
async def process_document(
    doc_id: str,
    session_id: str = Form(...),
    force: bool = Query(
        False,
        description="Si True, reprocesa aunque esté ANALYZED: borra vectores del doc y vuelve a extraer (Excel→partidas, PDF→OCR).",
    ),
):
    """
    Lanza extracción + indexación de un documento.
    Con force=true permite re-ingestar tras cambios de pipeline sin borrar el archivo.
    """
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    doc_data = await memory.get_document(doc_id)
    if not doc_data:
        await memory.disconnect()
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    
    current_status = doc_data.get("content", {}).get("status")
    if current_status == "ANALYZED" and not force:
        await memory.disconnect()
        return GenericResponse(success=True, message="Documento ya analizado.", data=doc_data["content"])

    if force:
        try:
            vc = VectorDbServiceClient()
            vc.delete_by_doc_id(session_id, doc_id)
        except Exception as e:
            print(f"WARN process_document force: no se pudieron limpiar vectores previos: {e}")

    file_path = doc_data["content"]["file_path"]
    filename = doc_data["content"]["filename"]
    ext = filename.lower().split(".")[-1]

    # Procesamiento Diferenciado por Tipo de Archivo
    if ext in ["xlsx", "xls"]:
        from app.services.document_excel_ingest import process_excel_document

        try:
            print(f"[*] Procesando Excel: {filename}")
            ocr_result, _ = await process_excel_document(
                memory, session_id, doc_id, file_path, filename
            )
        except Exception as e:
            await memory.disconnect()
            raise HTTPException(status_code=500, detail=f"Error procesando Excel: {str(e)}")
    else:
        # ARQUITECTURA DOBLE AGENTE EXTRACTOR
        from app.agents.extractor_digital import DigitalExtractorAgent
        from app.agents.extractor_vision import VisionExtractorAgent

        digital_agent = DigitalExtractorAgent()
        vision_agent = VisionExtractorAgent()
        
        # AGENTE 1: Intento Digital Rápido (Criterio: nativo o híbrido leíble)
        ocr_result = await digital_agent.extract(file_path)
        
        # AGENTE 2: Si el PDF es un escaneo cerrado (o imagen pura), se activa la Visión
        if not ocr_result.get("success", False):
            print(f"[*] 🚜 Delegando archivo pesado a VisionExtractorAgent...")
            ocr_result = await vision_agent.extract(file_path)

    if not ocr_result.get("success", False) or "error" in ocr_result:
        await memory.disconnect()
        error_detail = ocr_result.get('error', 'Fallo desconocido en la cadena de Extracción.')
        raise HTTPException(status_code=502, detail=f"Fallo en Extracción: {error_detail}")

    raw_text = ocr_result.get("extracted_text", "").strip()
    
    # --- GUARDA DE SEGURIDAD (HARDENING) ---
    # Validar que la extracción sea significativa para PDFs e Imágenes
    if ext not in ["xlsx", "xls"] and len(raw_text) < 100:
        await memory.disconnect()
        raise HTTPException(
            status_code=502, 
            detail="Extracción Insuficiente: El documento no contiene suficiente texto legible (<100 chars)."
        )

    pages = ocr_result.get("pages", [])

    # Indexación Vectorial
    vector_client = VectorDbServiceClient()
    for page in pages:
        p_text = page.get("text", "")
        if not p_text: continue
        chunk_size = 4000 if ext in ["xlsx", "xls"] else 800
        chunks = _chunk_text(p_text, chunk_size=chunk_size, overlap=200)
        metadatas = [{"source": filename, "session_id": session_id, "page": page.get("page"), "doc_id": doc_id} for _ in chunks]
        vector_client.add_texts(session_id, chunks, metadatas)

    # Actualizar Estado en DB
    updated_content = doc_data["content"]
    updated_content["status"] = "ANALYZED"
    updated_content["total_pages"] = ocr_result.get("total_pages", 1)
    updated_content["extracted_text"] = raw_text # Persistir el texto completo para los agentes
    
    await memory.save_document(doc_id, session_id, updated_content, {"status": "ANALYZED", "filename": filename})
    await memory.disconnect()

    return GenericResponse(success=True, message=f"Documento '{filename}' analizado con éxito.")

@router.get("/list/{session_id}", response_model=GenericResponse)
async def list_documents(session_id: str):
    """Lista todos los documentos asociados a una sesión."""
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
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
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    try:
        rows = await memory.get_line_items_for_session(session_id)
        return GenericResponse(
            success=True,
            message=f"{len(rows)} partida(s) tabular(es) en la sesión.",
            data={"count": len(rows), "items": rows},
        )
    finally:
        await memory.disconnect()


@router.delete("/{doc_id}", response_model=GenericResponse)
async def delete_document(doc_id: str, session_id: str = Form(...)):
    """Elimina una fuente del sistema (Archivo, DB y Vectores)."""
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
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
