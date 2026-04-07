import os
import sys
import asyncio
import json

# Rutas dentro del contenedor Backend
sys.path.append("/app")
from app.services.ocr_service import OCRServiceClient
from app.services.vector_service import VectorDbServiceClient

async def force_extraction_and_index():
    print("[FORCE] 🏗️ Iniciando Bypass de Extracción para ISSSTE LEÓN...")
    
    # 1. Ruta del archivo dentro de Docker
    # Asumiendo que ya lo copiamos a /app/data/inputs/vigilancia.pdf
    # En el sistema real, el backend usa UPLOAD_DIR
    pdf_path = "/app/data/inputs/vigilancia.pdf"
    session_id = "isste_leon_vigilancia"
    
    if not os.path.exists(pdf_path):
        print(f"[ERROR] No se encuentra el PDF en {pdf_path}")
        return

    # 2. Invocar el Servicio OCR (Columna Vertebral)
    print("[*] Llamando al motor OCR VLM...")
    ocr = OCRServiceClient()
    result = await ocr.scan_document(pdf_path)
    
    if "error" in result:
        print(f"[FAIL] Error en OCR: {result['error']}")
        return

    text = result.get("extracted_text", "")
    pages = result.get("pages", [])
    print(f"[OK] Extracción exitosa: {len(pages)} páginas, {len(text)} caracteres.")

    # 3. Inyectar en el Cerebro (VectorDB)
    print("[*] Indexando en base de datos de vectores...")
    vdb = VectorDbServiceClient()
    
    def _chunk_text(text, size=800, overlap=200):
        chunks = []
        for i in range(0, len(text), size - overlap):
            chunks.append(text[i:i + size])
        return chunks

    count = 0
    for pg in pages:
        p_text = pg.get("text", "")
        if not p_text: continue
        chunks = _chunk_text(p_text)
        metas = [{"source": "vigilancia.pdf", "page": pg.get("page"), "session_id": session_id} for _ in chunks]
        vdb.add_texts(session_id, chunks, metas)
        count += len(chunks)
        print(f"    [+] Pág {pg.get('page')} indexada ({len(chunks)} chunks)")

    print(f"\n[FUEGO] 🥇 Misión Cumplida: {count} Chunks inyectados en {session_id}.")
    print("El Auditor ya puede proceder con datos reales.")

if __name__ == "__main__":
    asyncio.run(force_extraction_and_index())
