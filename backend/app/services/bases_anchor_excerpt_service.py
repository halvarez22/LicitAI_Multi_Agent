"""
F12.2 — Excerpt de bases desde evidence_anchor_v1 (muéstrame el párrafo).

Fail-closed: sin ancla usable no inventa página; degrada a mensaje UX.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.evidence_anchor_service import (
    claim_quality_for_ux,
    extract_anchor_from_pending_question,
    extract_anchor_from_session_for_track,
    is_claim_locus_visible,
    load_pliego_pedagogico_ux_messages,
)


_SHOW_PARAGRAPH_MARKERS = (
    "muestrame el parrafo",
    "muéstrame el párrafo",
    "muestrame el párrafo",
    "muéstrame el parrafo",
    "ver el parrafo",
    "ver el párrafo",
    "ver paragrafo",
    "pasame el parrafo",
    "pásame el párrafo",
    "mostrar el parrafo",
    "mostrar el párrafo",
    "ver en bases",
    "mostrar en bases",
)


def detect_show_paragraph_intent(query: str) -> bool:
    """True si el usuario pide ver el párrafo de las bases ligado al claim activo."""
    from app.services.chat_user_intent import normalize_for_intent

    q = normalize_for_intent(query or "")
    if len(q) < 6:
        return False
    return any(normalize_for_intent(m) in q for m in _SHOW_PARAGRAPH_MARKERS)


def resolve_active_claim_anchor(
    session_state: Dict[str, Any],
    pending_questions: Optional[List[Dict[str, Any]]] = None,
    current_idx: int = 0,
) -> Dict[str, Any]:
    """
    Cascada: last_chat_claim → pending actual → briefing first_action → track económico.
    """
    state = session_state if isinstance(session_state, dict) else {}
    last = state.get("last_chat_claim_v1")
    if isinstance(last, dict) and isinstance(last.get("evidence_anchor"), dict):
        return last["evidence_anchor"]

    pending = list(pending_questions or state.get("pending_questions") or [])
    if pending and 0 <= current_idx < len(pending):
        anchor = extract_anchor_from_pending_question(pending[current_idx])
        if claim_quality_for_ux(anchor) in ("verified", "document_only"):
            return anchor

    briefing = state.get("convocatoria_briefing_v1")
    if isinstance(briefing, dict):
        action = briefing.get("recommended_first_action")
        if isinstance(action, dict) and isinstance(action.get("evidence_anchor"), dict):
            return action["evidence_anchor"]
        track = str(briefing.get("recommended_first_track") or "economic")
        return extract_anchor_from_session_for_track(state, track)

    return extract_anchor_from_session_for_track(state, "economic")


async def fetch_excerpt_from_evidence_anchor(
    session_id: str,
    anchor: Dict[str, Any],
    *,
    memory: Any = None,
    session_state: Optional[Dict[str, Any]] = None,
    vector_db: Any = None,
) -> Dict[str, Any]:
    """
    Obtiene ``bases_excerpt_v1`` a partir de ancla canónica.
    """
    quality = claim_quality_for_ux(anchor)
    msgs = load_pliego_pedagogico_ux_messages()
    if quality == "insufficient" or not is_claim_locus_visible(anchor):
        return {
            "schema_version": "bases_excerpt_v1",
            "available": False,
            "reason": "insufficient_anchor",
            "user_message": str(
                msgs.get("excerpt_unavailable")
                or "Aún no localicé la página exacta en las bases para este requisito. "
                "Puedes preguntarme por una palabra clave del pliego (ej. «integración del precio unitario»)."
            ),
            "evidence_anchor": anchor,
        }

    snippet = str(anchor.get("snippet") or "").strip()
    page = anchor.get("page")
    source = str(anchor.get("source_name") or "").strip() or None

    if page and vector_db is not None and (not snippet or len(snippet) < 20):
        try:
            docs = vector_db.fetch_page_documents(session_id, source or "", int(page))
            if docs:
                snippet = str(docs[0].get("page_content") or docs[0].get("text") or "")[:400]
        except Exception:
            pass

    if not snippet:
        return {
            "schema_version": "bases_excerpt_v1",
            "available": False,
            "reason": "missing_snippet",
            "user_message": str(
                msgs.get("excerpt_unavailable")
                or "Encontré la referencia pero no el párrafo indexado. Prueba preguntando por el tema en las bases."
            ),
            "evidence_anchor": anchor,
        }

    from app.services.forensic_risk_bases_excerpt_service import fetch_bases_excerpt_v1

    excerpt = await fetch_bases_excerpt_v1(
        session_id,
        snippet,
        page=page,
        source=source,
        session_state=session_state,
        memory=memory,
    )
    if isinstance(excerpt, dict):
        excerpt = dict(excerpt)
        excerpt["evidence_anchor"] = anchor
        if excerpt.get("available") and page and not excerpt.get("page"):
            excerpt["page"] = page
    return excerpt


def build_show_paragraph_chat_message(
    excerpt: Dict[str, Any],
    *,
    reminder_label: str = "",
) -> str:
    """Mensaje Gate 5 / pedagogía cuando el usuario pide el párrafo."""
    msgs = load_pliego_pedagogico_ux_messages()
    if not excerpt.get("available"):
        body = str(excerpt.get("user_message") or msgs.get("excerpt_unavailable") or "")
    else:
        page = excerpt.get("page") or (excerpt.get("evidence_anchor") or {}).get("page")
        para = str(excerpt.get("paragraph") or excerpt.get("page_text_truncated") or "").strip()
        if len(para) > 600:
            para = para[:597] + "…"
        locus = f"pág. {page}" if page else "bases"
        body = (
            f"Así lo señala el pliego ({locus}):\n\n"
            f"«{para}»"
        )
    if reminder_label:
        body = f"{body}\n\nCuando quieras, seguimos con: **{reminder_label}**."
    return body.strip()
