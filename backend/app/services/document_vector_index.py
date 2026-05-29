"""
Indexación canónica de páginas OCR/DOC en ChromaDB (un vector por página).
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.observability import get_logger
from app.services.vector_service import VectorDbServiceClient

logger = get_logger(__name__)


def index_pages_atomic(
    session_id: str,
    doc_id: str,
    filename: str,
    pages: List[Dict[str, Any]],
    vector_client: VectorDbServiceClient | None = None,
) -> int:
    """
    Indexa cada página como bloque atómico con cabecera [FUENTE|PÁGINA].

    Returns:
        Número de chunks indexados.
    """
    client = vector_client or VectorDbServiceClient()
    indexed = 0
    for page in pages or []:
        p_num = page.get("page", 0)
        p_raw_text = (page.get("text") or "").strip()
        if not p_raw_text:
            continue
        header = f"[FUENTE: {filename} | PÁGINA: {p_num}]\n"
        full_page_chunk = header + p_raw_text
        metadatas = [
            {
                "source": filename,
                "session_id": session_id,
                "page": p_num,
                "doc_id": doc_id,
                "chunk_type": "page_atomic",
            }
        ]
        client.add_texts(session_id, [full_page_chunk], metadatas)
        indexed += 1
        logger.info(
            "document_vector_index_page",
            session_id=session_id,
            filename=filename[:80],
            page=p_num,
        )
    return indexed
