"""
Normalización de texto de machotes extraídos de PDF/OCR (HRU universal).
"""
from __future__ import annotations

import re

# Línea con una sola palabra en mayúsculas (artefacto OCR).
_OCR_FRAGMENT_LINE_RE = re.compile(
    r"^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\-]{0,2}$"
)


def _is_ocr_caps_fragment(stripped: str) -> bool:
    """True si la línea parece palabra suelta partida por OCR."""
    if not stripped or len(stripped) > 48:
        return False
    if stripped.endswith(".") and len(stripped) > 28:
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return len(stripped) <= 4
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.85:
        return False
    words = stripped.split()
    return len(words) <= 4


def normalize_official_template_text(text: str) -> str:
    """
    Recompone párrafos rotos por OCR antes de rellenar o escribir DOCX.

    Une líneas de una sola palabra, preserva párrafos en blanco y limpia espacios.
    """
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = raw.split("\n")
    merged: list[str] = []
    buf: list[str] = []

    def _flush_buf() -> None:
        nonlocal buf
        if buf:
            merged.append(" ".join(buf))
            buf = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            _flush_buf()
            if merged and merged[-1] != "":
                merged.append("")
            continue
        if _OCR_FRAGMENT_LINE_RE.match(stripped) and len(stripped) <= 14:
            buf.append(stripped)
            continue
        if _is_ocr_caps_fragment(stripped):
            buf.append(stripped)
            continue
        _flush_buf()
        merged.append(stripped)
    _flush_buf()

    out = "\n".join(merged)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r" *\n *", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # «NUM.» en una línea y clave en la siguiente
    out = re.sub(r"(?i)(num\.?)\s*\n\s*([A-Z]/\d)", r"\1 \2", out)
    out = re.sub(r"(?i)(licitaci[oó]n\s+p[uú]blica\s+num\.?)\s*\n\s*", r"\1 ", out)
    return out.strip()


def is_boilerplate_obra_capture(text: str) -> bool:
    """True si el fragmento capturado no es denominación de obra sino texto legal."""
    low = str(text or "").lower()
    markers = (
        "se sujetar",
        "ley de obra",
        "disposiciones jur",
        "reglamento de obra",
        "manifestamos nuestro inter",
        "adquirimos las bases",
    )
    return any(m in low for m in markers)
