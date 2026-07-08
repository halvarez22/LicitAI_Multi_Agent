"""
Validación universal de citas del analista contra el corpus documental de la sesión.

Evita preguntas «fantasma» por few-shot del prompt o placeholders no verificables.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

from app.services.junta_bases_corpus import (
    BasesCorpus,
    corpus_contains_phrase,
    corpus_page_text,
    session_has_filename,
)

# Artefactos del esquema JSON de ejemplo del Analista (no son requisitos de ninguna licitación)
_ANALYST_FEW_SHOT_ARTIFACT_RE = re.compile(
    r"(?i)cl[aá]usula\s+4\.2.*p[aá]gina\s+18.*"
    r"(?:12\s*a[nñ]os?).*(?:3\s*a[nñ]os?|anexo\s+t[eé]cnico)"
)

_PLACEHOLDER_SNIPPET_RE = re.compile(
    r"(?i)fragmento id[eé]ntico al p[aá]rrafo citado|"
    r"texto literal copiado de las bases sin abreviar|"
    r"^\s*\.\.\.\s*$"
)

_GENERIC_BASES_FILENAME_RE = re.compile(
    r"(?i)^bases[_\s-]*convocatoria\.pdf$"
)


def is_analyst_few_shot_artifact(text: str) -> bool:
    """Detecta la pregunta/plantilla del ejemplo del prompt del Analista."""
    return bool(_ANALYST_FEW_SHOT_ARTIFACT_RE.search(str(text or "")))


def is_placeholder_snippet(text: str) -> bool:
    return bool(_PLACEHOLDER_SNIPPET_RE.search(str(text or "").strip()))


def _extract_significant_numbers(text: str) -> List[str]:
    return [m.group(1) for m in re.finditer(r"\b(\d{1,3})\b", str(text or ""))]


def analyst_question_supported(
    pregunta: str,
    corpus: BasesCorpus,
    analysis: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    True si la pregunta del analista puede sustentarse en corpus o requisitos verificados.

    Rechaza artefactos del few-shot y afirmaciones numéricas ausentes del expediente.
    """
    p = str(pregunta or "").strip()
    if not p:
        return False
    if is_analyst_few_shot_artifact(p):
        return False

    nums = _extract_significant_numbers(p)
    experience_nums = [n for n in nums if int(n) >= 1 and int(n) <= 40]
    if len(experience_nums) >= 2:
        if not _dual_years_in_corpus_or_analysis(p, corpus, analysis):
            return False

    if corpus.segments:
        substantive = re.sub(r"(?i)con respecto|establece que|cuál de estos", " ", p)
        substantive = re.sub(r"[^a-z0-9áéíóúñ ]", " ", substantive)
        words = [w for w in substantive.split() if len(w) >= 8]
        if words and not any(corpus_contains_phrase(corpus, w, min_len=8) for w in words[:4]):
            if not _has_verified_requisito_literal(analysis, p):
                return False
    return True


def _year_in_experience_context(text: str, year: str) -> bool:
    """True si el año aparece ligado a «experiencia» o «años» (no como número de sección suelto)."""
    t = str(text or "")
    patterns = (
        rf"(?<=[^\d]){year}\s*a(?:ñ|n)os",
        rf"experiencia[^.]{{0,40}}{year}",
        rf"{year}[^.]{{0,40}}experiencia",
    )
    return any(re.search(p, t, re.I) for p in patterns)


def _dual_years_in_corpus_or_analysis(
    pregunta: str,
    corpus: BasesCorpus,
    analysis: Optional[Dict[str, Any]],
) -> bool:
    nums = sorted({int(n) for n in _extract_significant_numbers(pregunta) if 1 <= int(n) <= 40})
    if len(nums) < 2:
        return True
    if corpus.segments and corpus.combined:
        found = sum(1 for n in nums if _year_in_experience_context(corpus.combined, str(n)))
        if found >= 2:
            return True
    if analysis:
        hits = 0
        for req in analysis.get("requisitos_participacion") or []:
            if not isinstance(req, dict):
                continue
            txt = str(req.get("texto_literal") or req.get("texto") or "")
            if is_placeholder_snippet(txt):
                continue
            for n in nums:
                if _year_in_experience_context(txt, str(n)):
                    hits += 1
        if hits >= 2:
            return True
    return False


def _has_verified_requisito_literal(analysis: Optional[Dict[str, Any]], pregunta: str) -> bool:
    if not isinstance(analysis, dict):
        return False
    pn = re.sub(r"\s+", " ", pregunta.lower())
    for req in analysis.get("requisitos_participacion") or []:
        if not isinstance(req, dict):
            continue
        txt = str(req.get("texto_literal") or req.get("texto") or "").strip()
        if len(txt) < 20 or is_placeholder_snippet(txt):
            continue
        if txt.lower()[:40] in pn or pn[:40] in txt.lower():
            return True
    return False


def gap_item_supported(gap: Dict[str, Any], corpus: BasesCorpus) -> bool:
    """Valida un ítem de gap_analysis antes de convertirlo en pregunta de junta."""
    req = str(gap.get("requisito") or "").strip()
    evid = str(gap.get("evidence_snippet") or "").strip()
    archivo = str(gap.get("archivo_fuente") or "").strip()

    if is_placeholder_snippet(req) and is_placeholder_snippet(evid):
        return False
    if is_analyst_few_shot_artifact(req) or is_analyst_few_shot_artifact(evid):
        return False
    if archivo and _GENERIC_BASES_FILENAME_RE.match(archivo) and corpus.filenames:
        if not session_has_filename(corpus, archivo):
            return False

    if corpus.segments and req and len(req) >= 16:
        if not corpus_contains_phrase(corpus, req, min_len=16):
            if not is_placeholder_snippet(evid) and evid and corpus_contains_phrase(corpus, evid, min_len=16):
                return True
            if re.search(r"\d+\s*a[nñ]os", req, re.I) and not _years_in_corpus(req, corpus):
                return False
    return True


def _years_in_corpus(text: str, corpus: BasesCorpus) -> bool:
    for m in re.finditer(r"(\d{1,2})\s*a(?:ñ|n)os", str(text or ""), re.I):
        if _year_in_experience_context(corpus.combined, m.group(1)):
            return True
    return False


def requisito_literal_supported(req: Dict[str, Any], corpus: BasesCorpus) -> bool:
    txt = str(req.get("texto_literal") or req.get("texto") or "").strip()
    if is_placeholder_snippet(txt):
        return False
    if len(txt) < 12:
        return False
    if corpus.segments:
        return corpus_contains_phrase(corpus, txt, min_len=12)
    return True


def _accent_fold(text: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", str(text or ""))
        if unicodedata.category(c) != "Mn"
    )


def _tokenize_substantive(text: str, *, min_len: int = 4) -> List[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9]+", _accent_fold(text.lower()))
        if len(w) >= min_len
    ]


def _consecutive_token_run_at_citation_start(
    citation: str,
    target: str,
    *,
    run_len: int = 3,
) -> bool:
    """True si los primeros tokens de la cita aparecen consecutivos en el texto objetivo."""
    words = _tokenize_substantive(citation, min_len=4)
    if len(words) < 2:
        return False
    need = min(run_len, len(words))
    tokens = _tokenize_substantive(target, min_len=4)
    if len(tokens) < need:
        return False
    head = words[:need]
    for i in range(len(tokens) - need + 1):
        if tokens[i : i + need] == head:
            return True
    return False


def _extract_content_words(text: str, *, min_len: int = 5) -> List[str]:
    cleaned = re.sub(r"[^a-z0-9áéíóúñ ]", " ", str(text or "").lower())
    return [w for w in cleaned.split() if len(w) >= min_len][:8]


def _phrase_overlap_in_text(phrase: str, target: str, *, min_hits: int = 2) -> bool:
    words = _extract_content_words(phrase, min_len=5)
    if not words:
        return True
    blob = re.sub(r"\s+", " ", str(target or "").lower())
    hits = sum(1 for w in words if w in blob)
    need = min(min_hits, len(words))
    return hits >= need


_GENERIC_ALERT_MOTIVO_RE = re.compile(
    r"(?i)falta de informaci[oó]n|imposibiliten determinar|riesgo de descalific|"
    r"incertidumbre para integrar"
)


def _alert_citation_text(alert: Dict[str, Any]) -> str:
    """Texto que se cita en la pregunta: prioriza la frase literal más específica."""
    motivo = str(alert.get("motivo") or "").strip()
    sug = str(alert.get("sugerencia") or "").strip()
    if sug and _GENERIC_ALERT_MOTIVO_RE.search(motivo):
        return sug
    if sug and len(sug) > len(motivo) + 8:
        return sug
    return motivo or sug


def alert_item_supported(alert: Dict[str, Any], corpus: BasesCorpus) -> bool:
    """
    Valida alertas de descalificación: motivo sustentado en corpus y, si hay página, en esa página.
    """
    motivo = str(alert.get("motivo") or "").strip()
    sug = str(alert.get("sugerencia") or "").strip()
    citation = _alert_citation_text(alert)
    text = citation or motivo or sug
    if not text:
        return False
    if is_placeholder_snippet(text) or is_analyst_few_shot_artifact(text):
        return False

    pag_raw = alert.get("pagina")
    pag: Optional[int] = None
    if pag_raw not in (None, ""):
        try:
            pag = int(str(pag_raw).strip())
        except ValueError:
            pag = None

    if pag is not None and corpus.segments:
        page_text = corpus_page_text(corpus, pag)
        if not page_text.strip():
            return False
        if not citation:
            return False
        page_norm = re.sub(r"\s+", " ", _accent_fold(page_text).lower())
        cit_norm = re.sub(r"\s+", " ", _accent_fold(citation).lower())
        if len(cit_norm) >= 16 and cit_norm in page_norm:
            return True
        if not _consecutive_token_run_at_citation_start(citation, page_text, run_len=3):
            return False
        return True

    if corpus.segments and citation and len(citation) >= 12:
        if corpus_contains_phrase(corpus, citation, min_len=12):
            return True
        words = _extract_content_words(citation, min_len=6)
        if words and not any(corpus_contains_phrase(corpus, w, min_len=6) for w in words[:5]):
            return False
    return True
