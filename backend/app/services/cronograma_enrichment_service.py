"""
Reconstruye el cronograma del Analista desde fragmentos RAG cuando la salida LLM quedó en placeholders.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.agents.analyst import normalize_cronograma_dict
from app.core.logging_config import get_logger
from app.services.analyst_participacion_enrichment import is_placeholder_analyst_text

logger = get_logger(__name__)

_HITO_RAG_QUERIES: Dict[str, str] = {
    "publicacion_convocatoria": "publicación convocatoria CompraNet fecha",
    "visita_instalaciones": "visita a instalaciones días horario",
    "junta_aclaraciones": "junta de aclaraciones se llevará a cabo el día",
    "presentacion_proposiciones": "presentación y apertura de proposiciones entregarse a más tardar",
    "fallo": "fallo se llevará a cabo el día hora",
    "firma_contrato": "firma del contrato el día horas",
}

_SOURCE_HEADER_RE = re.compile(r"\[FUENTE:[^\]]+\]\s*", re.IGNORECASE)
_DATE_IN_TEXT_RE = re.compile(
    r"\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}", re.IGNORECASE
)

# Patrones sobre texto de bases (español MX); deben capturar fecha en la oración.
_HITO_EXTRACTORS: Dict[str, Tuple[str, ...]] = {
    "publicacion_convocatoria": (
        r"(?is)(publicaci[oó]n\s+de\s+la\s+convocatoria[^.\n]{0,220}?\d{1,2}[^.\n]{0,80}\.)",
        r"(?is)(convocatoria[^.\n]{0,120}?\d{1,2}\s+de\s+\w+\s+de\s+20\d{2}[^.\n]{0,80}\.)",
    ),
    "visita_instalaciones": (
        r"(?is)(las?\s+visitas\s+se\s+llevar[aá]n\s+a\s+cabo[^.]+\.)",
        r"(?is)(visitas?\s+a\s+instalaciones[^.]+\d{1,2}[^.]+\.)",
        r"(?is)(visita\s+(?:a[l]?\s+)?(?:el\s+)?(?:sitio|instalaciones)[^.]{0,120}?se\s+llevar[aá]\s+a\s+cabo[^.]+\.)",
        r"(?is)(se\s+llevar[aá]\s+a\s+cabo\s+(?:el\s+)?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
    ),
    "junta_aclaraciones": (
        r"(?is)(junta\s*\(?s?\)?\s+de\s+aclaraciones[^.]{0,200}?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
        r"(?is)(se\s+llevar[aá]\s+a\s+cabo\s+(?:el\s+)?(?:d[ií]a\s+)?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
    ),
    "presentacion_proposiciones": (
        r"(?is)(presentaci[oó]n\s+y\s+apertura\s+de\s+proposiciones[^.]{0,280}?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
        r"(?is)(entregarse\s+a\s+m[aá]s\s+tardar\s+(?:el\s+)?(?:d[ií]a\s+)?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
        r"(?is)(se\s+llevar[aá]\s+a\s+cabo\s+(?:el\s+)?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
    ),
    "fallo": (
        r"(?is)(fallo[^.]{0,80}?se\s+llevar[aá]\s+a\s+cabo\s+(?:el\s+)?(?:d[ií]a\s+)?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
        r"(?is)((?:celebrar[aá]\s+el\s+)?acto\s+de\s+fallo[^.]{0,160}?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
        r"(?is)(\bg\)\s*fallo\b[^.]{0,220}?\d{1,2}\s+de\s+\w+\s+(?:de|del)\s+20\d{2}[^.]+\.)",
    ),
    "firma_contrato": (
        r"(?is)(firmar\s+el\s+contrato\s+el\s+d[ií]a\s+\d{1,2}\s+de\s+\w+\s+de\s+20\d{2}[^.]+\.)",
        r"(?is)(\bh\)\s*firma\s+del\s+contrato\b[^.]{0,200}?\d{1,2}\s+de\s+\w+\s+de\s+20\d{2}[^.]+\.)",
    ),
}

_BASES_SOURCE_HINTS = ("bases", "convocatoria", "pliego")
_LOW_PRIORITY_SOURCES = ("aclaraciones.pdf", "acta de inicio", "tren maya")

_SOURCE_HEADER_RE = re.compile(r"\[FUENTE:[^\]]+\]\s*", re.IGNORECASE)


def is_placeholder_cronograma_value(val: Any) -> bool:
    """True si el valor no aporta fecha utilizable para la UI."""
    s = str(val or "").strip()
    if not s:
        return True
    low = s.lower()
    if low in {
        "...",
        "no especificado",
        "fecha no especificada",
        "sin fecha",
        "n/e",
        "—",
        "-",
        "por definir",
        "según bases",
    }:
        return True
    if "no especificad" in low and not re.search(r"\d{1,2}\s+de\s+", low):
        return True
    if is_placeholder_analyst_text(s):
        return True
    # Debe contener al menos un dígito de año o día para considerarse útil
    if not re.search(r"\d", s):
        return True
    return False


def cronograma_needs_enrichment(cronograma: Any) -> bool:
    """True si la mayoría de hitos carecen de fechas reales."""
    norm = normalize_cronograma_dict(cronograma)
    vals = list(norm.values())
    if not vals:
        return True
    bad = sum(1 for v in vals if is_placeholder_cronograma_value(v))
    return bad >= max(3, (len(vals) + 1) // 2)


def _clean_extracted(text: str) -> str:
    s = _SOURCE_HEADER_RE.sub("", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 420:
        s = s[:417].rstrip() + "…"
    return s


def _snippet_priority(text: str) -> int:
    """Mayor puntaje = más probable que sea el calendario de las bases de la sesión."""
    low = str(text or "").lower()
    score = 0
    if any(h in low for h in _BASES_SOURCE_HINTS):
        score += 12
    if _DATE_IN_TEXT_RE.search(low):
        score += 4
    if any(bad in low for bad in _LOW_PRIORITY_SOURCES):
        score -= 8
    if "acta de inicio de junta" in low and "bases" not in low:
        score -= 6
    return score


def _rank_snippets(documents: List[Any]) -> List[str]:
    docs = [str(d) for d in documents if d]
    return sorted(docs, key=_snippet_priority, reverse=True)


def _bases_pages_blob(session_id: str, vdb: Any) -> str:
    """Fallback: páginas típicas del apartado III (formas y términos) en PDF de bases."""
    parts: List[str] = []
    for src in ("bases_0001.pdf", "bases.pdf", "Bases.pdf", "bases_convocatoria.pdf"):
        for pg in range(1, 14):
            try:
                for doc in vdb.fetch_page_documents(session_id, src, pg) or []:
                    parts.append(str(doc))
            except Exception:
                continue
    return "\n".join(parts)


def _extract_from_blob(hito_id: str, blob: str) -> Optional[str]:
    for pat in _HITO_EXTRACTORS.get(hito_id, ()):
        m = re.search(pat, blob)
        if m:
            cleaned = _clean_extracted(m.group(1))
            if cleaned and not is_placeholder_cronograma_value(cleaned):
                if _DATE_IN_TEXT_RE.search(cleaned) or hito_id == "visita_instalaciones":
                    return cleaned
    return None


def enrich_cronograma_from_rag(
    session_id: str,
    cronograma: Any,
    *,
    vector_db: Any = None,
    bases_text: Optional[str] = None,
) -> Dict[str, str]:
    """
    Completa hitos faltantes desde corpus de bases (determinista) y, si falta, RAG vectorial.

    Args:
        bases_text: Texto de bases/convocatoria de la sesión (p. ej. ``build_bases_corpus``).

    Returns:
        Cronograma normalizado con fechas literales cuando el RAG las localiza.
    """
    from app.services.cronograma_bases_extract import merge_cronograma_with_bases
    from app.services.vector_service import VectorDbServiceClient

    corpus = str(bases_text or "").strip()
    out = merge_cronograma_with_bases(cronograma, corpus) if corpus else normalize_cronograma_dict(cronograma)
    vdb = vector_db or VectorDbServiceClient()
    bases_blob = corpus or _bases_pages_blob(session_id, vdb)

    for hito_id, query in _HITO_RAG_QUERIES.items():
        if not is_placeholder_cronograma_value(out.get(hito_id)):
            continue
        try:
            res = vdb.query_texts(session_id, query, n_results=8)
            ranked = _rank_snippets(res.get("documents") or [])
            combined = "\n".join(ranked[:8])
            if bases_blob:
                combined = bases_blob + "\n" + combined
            found = _extract_from_blob(hito_id, combined)
            if found:
                out[hito_id] = found
        except Exception as exc:
            logger.warning(
                "cronograma_rag_hito_failed",
                session_id=session_id,
                hito_id=hito_id,
                error=str(exc)[:200],
            )
    return out


def cronograma_improved(before: Any, after: Dict[str, str]) -> bool:
    """True si el cronograma enriquecido tiene más hitos con fecha real."""
    b = normalize_cronograma_dict(before)
    good_before = sum(1 for v in b.values() if not is_placeholder_cronograma_value(v))
    good_after = sum(1 for v in after.values() if not is_placeholder_cronograma_value(v))
    return good_after > good_before


def cronograma_dates_changed(before: Any, after: Dict[str, str]) -> bool:
    """True si algún hito parseable cambió de fecha/hora (p. ej. corrección desde tabla de bases)."""
    from app.checklist.hito_scheduler import parse_fecha_hito

    b = normalize_cronograma_dict(before)
    a = normalize_cronograma_dict(after)
    for key in _HITO_RAG_QUERIES:
        pb = parse_fecha_hito(str(b.get(key) or ""))
        pa = parse_fecha_hito(str(a.get(key) or ""))
        if pa is not None and pb != pa:
            return True
    return False
