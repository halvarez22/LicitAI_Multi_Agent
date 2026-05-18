"""Utilidades de calidad OCR reutilizables en rutas/servicios."""
from __future__ import annotations

import re

_PAGE_MARKER_RE = re.compile(r"-{2,}\s*P[ÁA]GINA\s+\d+\s*-{2,}", re.IGNORECASE)
_NUMERIC_LINE_RE = re.compile(r"^\d{5,}$")
_MARKER_WORDS = {"PAGINA", "PÁGINA"}


def looks_like_low_signal_ocr(text: str) -> bool:
    """Detecta OCR con contenido sintético (paginación/marcadores sin semántica)."""
    t = (text or "").strip()
    if not t:
        return True
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return True
    marker_hits = sum(1 for ln in lines if _PAGE_MARKER_RE.search(ln))
    numeric_hits = sum(1 for ln in lines if _NUMERIC_LINE_RE.match(ln))
    alpha_chars = sum(1 for ch in t if ch.isalpha())
    alpha_ratio = alpha_chars / max(1, len(t))
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", t)
    unique_meaningful = {
        tok.upper()
        for tok in tokens
        if tok.upper() not in _MARKER_WORDS
    }

    too_many_markers = marker_hits >= max(3, len(lines) // 4)
    too_many_numeric = numeric_hits >= max(3, len(lines) // 4)
    too_little_semantic_text = alpha_ratio < 0.18 or len(unique_meaningful) < 5
    return (too_many_markers and too_little_semantic_text) or (too_many_numeric and too_little_semantic_text)

