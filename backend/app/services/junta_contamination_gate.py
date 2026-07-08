"""
Gate universal anti-contaminación para preguntas de junta de aclaraciones (HRU).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.junta_bases_corpus import BasesCorpus, junta_primary_corpus
from app.services.junta_citation_gate import is_analyst_few_shot_artifact

_JUNTA_CROSS_TENDER_RE = re.compile(
    r"(?i)(imss-bienestar|operario por turno|ap[eé]ndice\s+1\b|"
    r"la[\s\-]*07[\s\-]*h0m|007h0m|focon\s*0?4|patr[oó]n\s+sustituto)"
)

_JUNTA_INTERNAL_GAP_RE = re.compile(
    r"(?i)no se proporciona informaci[oó]n sobre el perfil|"
    r"verificar si la empresa tiene experiencia en servicios similares"
)

_JUNTA_GARBAGE_THEMATIC_RE = re.compile(
    r"(?i)constituci[oó]n\s+federal|art[ií]culo\s+16\s+de\s+la\s+constituci"
)


def passes_junta_question_gate(
    pregunta: str,
    *,
    corpus: Optional[BasesCorpus] = None,
    session_hint: str = "",
    source_ref: str = "",
    motivo: str = "",
) -> bool:
    """
    True si la pregunta puede mostrarse al portal de la convocante.

    Rechaza eco del few-shot del analista, PDFs ajenos y brechas internas de perfil.
    """
    from app.config.settings import settings

    blob = " ".join((pregunta, motivo, source_ref)).strip()
    if not blob or len(str(pregunta or "").strip()) < 12:
        return False
    if is_analyst_few_shot_artifact(pregunta):
        return False
    if _JUNTA_CROSS_TENDER_RE.search(blob):
        return False
    if _JUNTA_INTERNAL_GAP_RE.search(blob):
        return False
    if source_ref == "thematic_experience_years_conflict" and _JUNTA_GARBAGE_THEMATIC_RE.search(
        pregunta
    ):
        return False

    if not bool(getattr(settings, "JUNTA_CONTAMINATION_GATE_ENABLED", True)):
        return True

    primary = junta_primary_corpus(corpus) if corpus is not None else None

    if source_ref == "thematic_certification_scope" and primary is not None:
        from app.services.junta_thematic_discovery import _corpus_mentions_certification_cluster

        if not _corpus_mentions_certification_cluster(primary):
            return False

    if primary is not None and primary.segments:
        from app.services.document_deliverable_filter import snippet_contaminated_across_corpus

        if snippet_contaminated_across_corpus(pregunta[:280], primary):
            return False

    hint = str(session_hint or "").strip()
    if hint:
        try:
            from app.services.document_fill_quality_gate import detect_cross_tender_marker

            if detect_cross_tender_marker([pregunta, motivo], hint):
                return False
        except Exception:
            pass
    return True
