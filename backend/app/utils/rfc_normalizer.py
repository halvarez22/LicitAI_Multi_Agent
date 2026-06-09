"""
Normalización universal de RFC (México / SAT) sin hardcodes por contribuyente.

Elimina separadores habituales en OCR, UI y plantillas (espacios, guiones, puntos, barras)
y valida contra el patrón compacto persona moral (3) o física (4) + 6 dígitos + homoclave.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional

# Persona moral: 3 letras; persona física: 4 letras.
RFC_SAT_PATTERN = r"^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$"
RFC_SAT_RE = re.compile(RFC_SAT_PATTERN, re.IGNORECASE)

_RFC_LABEL_PREFIX_RE = re.compile(r"^(?:RFC|r\.f\.c\.)\s*:?\s*", re.IGNORECASE)
_RFC_FORMATTING_CHARS_RE = re.compile(r"[\s.\-/]")
_RFC_TOKEN_LOOSE_RE = re.compile(
    r"\b([A-Z&Ñ]{3,4})[\s.\-/]*(\d{6})[\s.\-/]*([A-Z0-9]{3})\b",
    re.IGNORECASE,
)


def strip_rfc_formatting(value: Any) -> str:
    """
    Quita prefijos «RFC:» y separadores cosméticos; no valida estructura SAT.

    Args:
        value: Texto crudo (str u otro convertible).

    Returns:
        Cadena compacta en mayúsculas (puede seguir siendo inválida como RFC).
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = _RFC_LABEL_PREFIX_RE.sub("", raw).strip()
    return _RFC_FORMATTING_CHARS_RE.sub("", raw).upper()


def normalize_rfc_sat(value: Any) -> Optional[str]:
    """
    Canoniza un RFC si, tras quitar formato, cumple el patrón SAT.

    Args:
        value: RFC en cualquier separación habitual.

    Returns:
        RFC compacto en mayúsculas, o ``None`` si no es válido.
    """
    compact = strip_rfc_formatting(value)
    if compact and RFC_SAT_RE.match(compact):
        return compact
    return None


def is_valid_rfc_sat(value: Any) -> bool:
    """True si ``normalize_rfc_sat`` produce un RFC válido."""
    return normalize_rfc_sat(value) is not None


def iter_rfcs_in_text(text: str) -> Iterable[str]:
    """
    Localiza tokens RFC en texto libre (párrafos OCR, DOCX, chat).

    Yields:
        RFC compactos válidos, sin duplicados consecutivos en el mismo fragmento.
    """
    seen: set[str] = set()
    for match in _RFC_TOKEN_LOOSE_RE.finditer(str(text or "")):
        candidate = f"{match.group(1)}{match.group(2)}{match.group(3)}".upper()
        if RFC_SAT_RE.match(candidate) and candidate not in seen:
            seen.add(candidate)
            yield candidate


def find_rfcs_in_text(text: str) -> List[str]:
    """Lista ordenada de RFC válidos detectados en ``text``."""
    return list(iter_rfcs_in_text(text))


def rfc_present_in_text(text: str, expected: Any) -> bool:
    """
    True si ``expected`` (normalizado) aparece en ``text`` en forma compacta o con separadores.
    """
    canon = normalize_rfc_sat(expected)
    if not canon:
        return False
    if canon in strip_rfc_formatting(text):
        return True
    return canon in set(find_rfcs_in_text(text))
