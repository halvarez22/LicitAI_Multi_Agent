"""
Salud de capa 1 (extracción/indexación) — independiente de compliance LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _doc_status(doc: Dict[str, Any]) -> str:
    content = doc.get("content") if isinstance(doc.get("content"), dict) else doc
    if not isinstance(content, dict):
        return ""
    return str(content.get("status") or "").upper()


def _doc_extracted_chars(doc: Dict[str, Any]) -> int:
    content = doc.get("content") if isinstance(doc.get("content"), dict) else doc
    if not isinstance(content, dict):
        return 0
    text = str(content.get("extracted_text") or "")
    return len(text.strip())


def compute_extraction_health(
    documents: Optional[List[Dict[str, Any]]],
    *,
    chroma_sources_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Evalúa si la materia prima (texto indexado) está lista.

    Universal: solo estados de documento y volumen de texto, sin reglas por convocante.
    """
    docs = [d for d in (documents or []) if isinstance(d, dict)]
    analyzed = 0
    pending = 0
    failed = 0
    total_chars = 0

    for doc in docs:
        st = _doc_status(doc)
        if st == "ANALYZED":
            analyzed += 1
            total_chars += _doc_extracted_chars(doc)
        elif st in ("UPLOADED", "PROCESSING", "PENDING"):
            pending += 1
        elif st in ("FAILED", "ERROR"):
            failed += 1

    has_chroma = chroma_sources_count is None or int(chroma_sources_count) > 0

    if analyzed == 0 and docs:
        status = "failed"
        msg = "No hay documentos de bases procesados (ANALYZED)."
    elif failed > 0:
        status = "failed"
        msg = "Al menos un documento falló en la extracción."
    elif pending > 0:
        status = "degraded"
        msg = "Hay documentos pendientes de procesar; el índice puede estar incompleto."
    elif analyzed > 0 and total_chars < 100:
        status = "failed"
        msg = "Extracción insuficiente: menos de 100 caracteres legibles."
    elif analyzed > 0 and not has_chroma:
        status = "degraded"
        msg = "Documentos analizados pero sin fuentes en el índice vectorial."
    else:
        status = "ok"
        msg = "Bases leídas e indexadas correctamente."

    return {
        "status": status,
        "documents_total": len(docs),
        "documents_analyzed": analyzed,
        "documents_pending": pending,
        "documents_failed": failed,
        "total_extracted_chars": total_chars,
        "chroma_sources_count": chroma_sources_count,
        "message_ux": msg,
    }


async def compute_extraction_health_for_session(memory: Any, session_id: str) -> Dict[str, Any]:
    """Wrapper async: lee documentos de sesión y opcionalmente Chroma."""
    documents: List[Dict[str, Any]] = []
    chroma_count: Optional[int] = None
    try:
        documents = await memory.get_documents(session_id) or []
    except Exception:
        documents = []
    try:
        from app.services.vector_service import VectorDbServiceClient

        chroma_count = len(VectorDbServiceClient().get_sources(session_id) or [])
    except Exception:
        chroma_count = None
    return compute_extraction_health(documents, chroma_sources_count=chroma_count)
