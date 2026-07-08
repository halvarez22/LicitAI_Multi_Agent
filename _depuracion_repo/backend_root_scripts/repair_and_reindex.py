"""
Reprocesa documentos de una sesión: vectores Chroma + (para Excel) session_line_items vía process_excel_document.

Uso (desde la carpeta backend o con PYTHONPATH):
  python repair_and_reindex.py SESSION_ID
  python repair_and_reindex.py la-51-gyn-051gyn025-n-8-2024_vigilancia

Opciones:
  --wipe-all-chromadb   Borra TODAS las colecciones Chroma (destructivo, multi-sesión).
                        Por defecto solo se eliminan vectores por doc_id de esta sesión antes de reindexar.

Docker (servicio backend, cwd /app):
  docker compose exec backend python repair_and_reindex.py SESSION_ID
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Raíz del backend (funciona en host y en /app del contenedor)
_ROOT = os.path.abspath(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.memory.factory import MemoryAdapterFactory
from app.services.ocr_service import OCRServiceClient
from app.services.vector_service import VectorDbServiceClient


async def repair(session_id: str, wipe_all_chromadb: bool) -> None:
    print("🚀 Iniciando REPARACIÓN Y RE-INDEXADO de LicitAI...")
    vector_client = VectorDbServiceClient()

    if wipe_all_chromadb:
        if not vector_client.client:
            print("⚠️ Chroma no disponible; se omite el wipe global.")
        else:
            print("🧹 Paso 1: Limpiando ChromaDB por completo (--wipe-all-chromadb)...")
            for c in vector_client.client.list_collections():
                print(f" - Eliminando colección: {c.name}")
                try:
                    vector_client.client.delete_collection(name=c.name)
                except Exception as e:
                    print(f"   WARN: {e}")
            print("✅ ChromaDB limpio.")
    else:
        print("ℹ️  Sin --wipe-all-chromadb: se borrarán solo los vectores por documento de esta sesión.")

    print(f"📂 Obteniendo documentos para sesión: {session_id}")
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    docs = await memory.get_documents(session_id)
    print(f"📄 Encontrados {len(docs)} documentos en la base de datos.")

    ocr_client = OCRServiceClient()

    for doc in docs:
        doc_id = doc["id"]
        content = doc.get("content") or {}
        filename = content.get("filename") or ""
        file_path = content.get("file_path")

        print(f"\n🔄 Procesando: {filename} ({doc_id})")

        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ ERROR: Archivo no encontrado en disco: {file_path}")
            continue

        ext = filename.split(".")[-1].lower() if filename else ""

        if ext in ["png", "jpg", "jpeg", "gif", "bmp"]:
            print(f"⏭️ Saltando indexación vectorial para imagen: {filename}")
            continue

        if not wipe_all_chromadb:
            try:
                vector_client.delete_by_doc_id(session_id, doc_id)
            except Exception as e:
                print(f"  WARN delete_by_doc_id: {e}")

        print(f"  🔍 Extrayendo texto/OCR...")
        if ext in ["xlsx", "xls"]:
            try:
                from app.services.document_excel_ingest import process_excel_document

                ocr_result, n_rows = await process_excel_document(
                    memory, session_id, doc_id, file_path, filename or ""
                )
                print(f"  📊 Partidas tabulares insertadas/reemplazadas: {len(n_rows)}")
            except Exception as e:
                print(f"  ❌ Error Excel (ingesta + partidas): {e}")
                continue
        else:
            ocr_result = await ocr_client.scan_document(file_path)

        if ocr_result.get("error"):
            print(f"  ❌ Error OCR: {ocr_result['error']}")
            continue

        pages = ocr_result.get("pages", [])
        print(f"  ✨ {len(pages)} páginas/hojas obtenidas.")

        raw_text = (ocr_result.get("extracted_text") or "").strip()
        updated_content = dict(content)
        updated_content["status"] = "ANALYZED"
        updated_content["extracted_text"] = raw_text
        updated_content["total_pages"] = ocr_result.get("total_pages", len(pages))
        meta = doc.get("metadata") or {}
        if isinstance(meta, dict):
            meta = {**meta, "status": "ANALYZED", "filename": filename}
        await memory.save_document(doc_id, session_id, updated_content, meta)

        print(f"  📦 Indexando vectores...")
        chunk_size = 12000
        for page in pages:
            p_text = page.get("text", "").strip()
            if not p_text:
                continue

            doc_type = "OTROS"
            name_lower = filename.lower()
            if any(kw in name_lower for kw in ["bases", "convocatoria"]):
                doc_type = "BASES"
            elif "constitutiva" in name_lower:
                doc_type = "CORPORATIVO"
            elif any(kw in name_lower for kw in ["anexo", "formato"]):
                doc_type = "ANEXO"
            elif "cif" in name_lower:
                doc_type = "LEGAL"

            if doc_type == "OTROS" and ext not in ["pdf", "xlsx", "xls", "doc", "docx"]:
                continue

            metadata = {
                "source": filename,
                "session_id": session_id,
                "page": page.get("page"),
                "doc_id": doc_id,
                "doc_type": doc_type,
            }

            if len(p_text) <= chunk_size:
                vector_client.add_texts(session_id, [p_text], [metadata])
            else:
                mid = len(p_text) // 2
                vector_client.add_texts(
                    session_id,
                    [p_text[: mid + 200], p_text[mid:]],
                    [metadata, metadata],
                )

    print("\n✅ REPARACIÓN FINALIZADA CON ÉXITO.")
    print(f"   Comprueba: GET .../upload/line-items/{session_id}")
    await memory.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description="Reindexar sesión y repoblar session_line_items (Excel).")
    p.add_argument("session_id", help="ID de la licitación (ej. la-51-gyn-051gyn025-n-8-2024_vigilancia)")
    p.add_argument(
        "--wipe-all-chromadb",
        action="store_true",
        help="Borra todas las colecciones Chroma (afecta a todas las sesiones).",
    )
    args = p.parse_args()
    asyncio.run(repair(args.session_id.strip(), args.wipe_all_chromadb))


if __name__ == "__main__":
    main()
