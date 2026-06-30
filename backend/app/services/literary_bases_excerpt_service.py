"""
Excerpt HRU para citas literales RAG (rag_literal_*) — texto indexado en Chroma, sin LLM.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.forensic_risk_bases_excerpt_service import fetch_bases_excerpt_v1


async def fetch_literary_bases_excerpt_v1(
    session_id: str,
    citation: Dict[str, Any],
    *,
    memory: Any = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Obtiene párrafo indexado para la viñeta literaria top (fail-closed si no hay ancla).

    ``citation`` debe incluir al menos ``literal``; opcional ``page`` y ``source``.
    """
    literal = str(citation.get("literal") or "").strip()
    if not session_id or not literal:
        return {
            "schema_version": "bases_excerpt_v1",
            "available": False,
            "reason": "missing_session_or_literal",
            "user_message": "No hay fragmento literario para anclar el párrafo en el índice.",
        }
    return await fetch_bases_excerpt_v1(
        session_id,
        literal,
        page=citation.get("page"),
        source=citation.get("source"),
        session_state=session_state,
        memory=memory,
    )
