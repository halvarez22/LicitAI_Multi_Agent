"""
Extracción HRU del párrafo completo desde el índice vectorial de la sesión.

Solo texto materializado en Chroma; sin LLM ni invención de contenido.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.economic_alert_classifier import alert_fingerprint
from app.services.forensic_risk_evidence_service import (
    _fetch_page_text,
    _normalize_index_source,
    _scan_index_for_literal,
    _snippet_from_doc,
    resolve_forensic_risk_evidence,
    verify_forensic_risk_evidence,
)

_SCHEMA = "bases_excerpt_v1"
_MAX_PAGE_CHARS = 12000
_MAX_PARAGRAPH_CHARS = 2400


def _sanitize_indexed_hru_text(text: str) -> str:
    """Quita metadatos de chunk indexados ([FUENTE:…], páginas sueltas) para UI HRU."""
    t = str(text or "")
    t = re.sub(r"\[FUENTE:[^\]]*\]\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(
        r"[^\[\n]{8,200}?\.pdf\s*\|\s*PÁGINA:\s*\d+\]",
        "",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\s*\|\s*PÁGINA:\s*\d+\]", "", t, flags=re.IGNORECASE)
    t = re.sub(r"---\s*PÁGINA\s+\d+\s*---", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*\d{1,3}\s*$", "", t, flags=re.MULTILINE)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _find_match_span(text: str, literal: str) -> tuple[int, int]:
    if not text or not literal:
        return -1, -1
    lit_norm = alert_fingerprint(literal)
    text_norm = alert_fingerprint(text)
    if lit_norm and lit_norm[:48] in text_norm:
        idx = text_norm.find(lit_norm[:48])
        if idx >= 0:
            ratio = len(text) / max(len(text_norm), 1)
            start = int(idx * ratio)
            return start, min(len(text), start + len(literal) + 80)
    for token in re.findall(r"\$[\d,]+(?:\.\d{2})?", literal):
        pos = text.lower().find(token.lower())
        if pos >= 0:
            return pos, pos + len(token)
        bare = token.replace(",", "").replace(".00", "")
        pos = text.replace(",", "").find(bare)
        if pos >= 0:
            return pos, pos + len(bare)
    return -1, -1


def _extract_paragraph(page_text: str, literal: str) -> str:
    if not page_text:
        return ""
    start, end = _find_match_span(page_text, literal)
    if start < 0:
        return page_text[: min(len(page_text), 800)].strip()

    paragraphs = re.split(r"\n\s*\n", page_text)
    if len(paragraphs) <= 1:
        paragraphs = re.split(r"(?<=[.;])\s+", page_text)

    for para in paragraphs:
        p = para.strip()
        if not p:
            continue
        ps, _ = _find_match_span(p, literal)
        if ps >= 0:
            if len(p) > _MAX_PARAGRAPH_CHARS:
                rel = max(0, ps - 200)
                return p[rel : rel + _MAX_PARAGRAPH_CHARS].strip()
            return p

    win_start = max(0, start - 400)
    win_end = min(len(page_text), end + 400)
    return page_text[win_start:win_end].strip()[:_MAX_PARAGRAPH_CHARS]


def _user_message_for_reason(reason: str, *, indexed_chunks: int = 0) -> str:
    if reason == "page_not_indexed" and indexed_chunks == 0:
        return (
            "El índice vectorial de esta sesión está vacío (0 fragmentos). "
            "Sube las bases o ejecuta reindexación; hasta entonces el riesgo solo puede explicarse "
            "desde el análisis económico, no desde un párrafo del PDF."
        )
    messages = {
        "page_not_indexed": (
            "No localizamos en el índice un párrafo con el monto del riesgo. "
            "El aviso lo sintetizó el agente económico; en el PDF la redacción suele ser distinta. "
            "Busca el monto en las bases o verifica que el PDF correcto esté indexado."
        ),
        "empty_page_content": (
            "La página detectada no tiene contenido recuperable en el índice. "
            "Reindexa las bases de la sesión."
        ),
        "missing_session_or_literal": "Faltan datos de sesión o literal para buscar el párrafo.",
    }
    return messages.get(reason, "No se encontró párrafo indexado para ese literal en la sesión.")


async def _ensure_index_ready(session_id: str, memory: Any, *, force: bool = False) -> None:
    if not memory:
        return
    try:
        from app.services.vector_sync_service import VectorSyncService
        from app.services.vector_service import VectorDbServiceClient

        vdb = VectorDbServiceClient()
        if force or vdb.count_session_chunks(session_id) == 0:
            await VectorSyncService().ensure_session_indexed(memory, session_id, force=force)
    except Exception:
        pass


async def fetch_bases_excerpt_v1(
    session_id: str,
    literal: str,
    *,
    page: Any = None,
    source: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    memory: Any = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Obtiene párrafo completo indexado para un literal de riesgo forense."""
    literal = str(literal or "").strip()
    if not session_id or not literal:
        reason = "missing_session_or_literal"
        return {
            "schema_version": _SCHEMA,
            "available": False,
            "reason": reason,
            "user_message": _user_message_for_reason(reason),
        }

    await _ensure_index_ready(session_id, memory)

    risk_ctx: Dict[str, Any] = {}
    if page is not None:
        risk_ctx["page"] = page
    if source:
        risk_ctx["source"] = source

    ev = dict(evidence or {})
    if not ev.get("page") and not ev.get("snippet"):
        ev = await resolve_forensic_risk_evidence(
            session_id,
            literal,
            risk_ctx=risk_ctx,
            session_state=session_state,
            memory=memory,
        )
    else:
        try:
            from app.services.vector_service import VectorDbServiceClient

            vdb = VectorDbServiceClient()
            ev = verify_forensic_risk_evidence(vdb, session_id, literal, ev)
        except Exception:
            pass

    page_val = page if page is not None else ev.get("page")
    source_val = ev.get("source")
    snippet_fallback = str(ev.get("snippet") or "").strip()

    page_text = ""
    resolved_source = source_val
    prov_source = "vector_index"
    indexed_chunks = 0
    try:
        from app.services.vector_service import VectorDbServiceClient

        vdb = VectorDbServiceClient()
        indexed_chunks = vdb.count_session_chunks(session_id)
        resolved_source = _normalize_index_source(vdb, session_id, source_val)

        if page_val is not None:
            page_text, resolved_source = _fetch_page_text(
                vdb,
                session_id,
                page_val,
                preferred_source=resolved_source,
                literal=literal,
            )

        if not page_text and page_val is None:
            scanned = _scan_index_for_literal(vdb, session_id, literal, source_filter=resolved_source)
            if not scanned:
                scanned = _scan_index_for_literal(vdb, session_id, literal)
            if scanned.get("page") is not None:
                page_val = scanned.get("page")
                resolved_source = _normalize_index_source(vdb, session_id, scanned.get("source"))
                page_text, resolved_source = _fetch_page_text(
                    vdb,
                    session_id,
                    page_val,
                    preferred_source=resolved_source,
                    literal=literal,
                )
                if page_text:
                    ev = {**ev, **scanned, "match_confidence": "alta"}
                    prov_source = "index_scan"

        if not page_text and snippet_fallback:
            page_text = snippet_fallback
            prov_source = ev.get("provenance") or "evidence_snippet"
    except Exception:
        page_text = snippet_fallback
        prov_source = ev.get("provenance") or "evidence_snippet"

    page_text = _sanitize_indexed_hru_text(page_text)
    snippet_fallback = _sanitize_indexed_hru_text(snippet_fallback)

    if not page_text:
        reason = "page_not_indexed" if page_val is None else "empty_page_content"
        try:
            source_count = len(vdb.get_sources(session_id) or [])
        except Exception:
            source_count = 0
        return {
            "schema_version": _SCHEMA,
            "available": False,
            "reason": reason,
            "user_message": _user_message_for_reason(reason, indexed_chunks=indexed_chunks),
            "literal": literal,
            "page": page_val,
            "source": resolved_source,
            "evidence_confidence": ev.get("match_confidence"),
            "diagnostics": {
                "indexed_chunks": indexed_chunks,
                "indexed_sources": source_count,
            },
        }

    paragraph = _sanitize_indexed_hru_text(_extract_paragraph(page_text, literal))
    if not paragraph and snippet_fallback:
        paragraph = snippet_fallback
    if not paragraph:
        paragraph = _sanitize_indexed_hru_text(
            _snippet_from_doc(literal, page_text, max_len=_MAX_PARAGRAPH_CHARS)
        )

    lit_fp = alert_fingerprint(literal)
    para_fp = alert_fingerprint(paragraph)
    if lit_fp and lit_fp[:48] not in para_fp and len(literal) >= 40:
        paragraph = literal[:_MAX_PARAGRAPH_CHARS].strip()

    excerpt_mode = "full_page" if page_val is not None and prov_source in ("vector_index", "index_scan") else "snippet_fallback"

    match_confidence = ev.get("match_confidence")
    para_fp_final = alert_fingerprint(paragraph)
    if lit_fp and lit_fp[:48] in para_fp_final:
        match_confidence = "alta"
    elif not match_confidence:
        if page_val is not None:
            match_confidence = "media"
        else:
            match_confidence = "baja"

    sanitized_page = page_text[:_MAX_PAGE_CHARS] if len(page_text) > _MAX_PAGE_CHARS else page_text

    return {
        "schema_version": _SCHEMA,
        "available": bool(paragraph),
        "literal": literal,
        "page": page_val,
        "source": resolved_source,
        "paragraph": paragraph,
        "excerpt_mode": excerpt_mode,
        "page_text_truncated": sanitized_page if len(page_text) > _MAX_PAGE_CHARS else None,
        "match_confidence": match_confidence,
        "provenance_ui": {
            "source": prov_source,
            "session_id": session_id,
            "page": page_val,
            "document": resolved_source,
        },
        "user_message": None,
    }
