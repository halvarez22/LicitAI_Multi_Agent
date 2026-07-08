import asyncio
import os
import sys
from app.services.vector_service import VectorDbServiceClient
from app.services.ocr_service import OCRServiceClient
from app.memory.factory import MemoryAdapterFactory

async def finalize():
    print("🚀 Iniciando INDEXACIÓN FINAL del documento ISSSTE BCS...")
    
    session_id = "ISSSTE-BCS-2024-OFFICIAL"
    file_path = "/data/uploads/00165194-7328-4bb5-a235-7f10ce882cf6_bases_servicio_limpieza_2024_issste_bcs.pdf"
    filename = "BASES SERVICIO LIMPIEZA 2024 ISSSTE BCS.pdf"

    # 1. Preparar memoria
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    
    # Asegurar sesión
    await memory.save_session(session_id, {"status": "active", "title": "Servicio Limpieza ISSSTE BCS 2024"})
    
    # Registrar documento si no existe o actualizarlo
    doc_id = "doc_issste_bcs_final_01"
    await memory.save_document(doc_id, session_id, {
        "status": "ANALYZING", 
        "filename": filename, 
        "file_path": file_path
    }, {"filename": filename})

    # 2. Extracción Inteligente (Usará PyMuPDF)
    print(f"[*] Extrayendo texto de: {filename}")
    ocr_client = OCRServiceClient()
    ocr_result = await ocr_client.scan_document(file_path)
    
    if "error" in ocr_result:
        print(f"❌ Error extracción: {ocr_result['error']}")
        await memory.disconnect()
        return

    # 3. Indexación Vectorial (ChromaDB)
    print(f"[*] Indexando en ChromaDB para sesión: {session_id}")
    vector_client = VectorDbServiceClient()
    pages = ocr_result.get("pages", [])
    
    for page in pages:
        p_text = page.get("text", "").strip()
        if not p_text: continue
        
        # Metadata enriquecida
        metadata = {
            "source": filename,
            "session_id": session_id,
            "page": page.get("page"),
            "doc_id": doc_id,
            "doc_type": "BASES" # Es el pliego de condiciones
        }
        
        # Chunking (Página completa para mantener contexto técnico)
        vector_client.add_texts(session_id, [p_text], [metadata])
    
    # 4. Actualizar estado final
    await memory.save_document(doc_id, session_id, {
        "status": "ANALYZED", 
        "filename": filename, 
        "file_path": file_path,
        "total_pages": len(pages)
    }, {"filename": filename, "status": "ANALYZED"})
    
    print(f"\n✅ INDEXACIÓN COMPLETADA: {len(pages)} páginas procesadas.")
    print(f"Session ID: {session_id}")
    print(f"Doc ID: {doc_id}")
    
    await memory.disconnect()

if __name__ == "__main__":
    asyncio.run(finalize())
