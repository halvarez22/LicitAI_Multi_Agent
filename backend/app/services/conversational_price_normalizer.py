"""
Normalización conversacional de precios (Ítem A).

Convierte respuestas en lenguaje natural a valor numérico canónico sin inventar precios.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

_NUM_WORDS = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "veintinueve": 29,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "mil": 1000,
    "millon": 1_000_000,
    "millón": 1_000_000,
}


def _strip_noise(raw: str) -> str:
    s = (raw or "").strip()
    s = re.sub(r"[\$€]", "", s, flags=re.I)
    s = re.sub(r"\b(mxn|pesos?|mn|sin\s+iva|con\s+iva|iva\s+incluido?)\b", "", s, flags=re.I)
    s = s.replace(",", "").strip()
    return s


def _parse_mil_pattern(s: str) -> Optional[float]:
    """Ej: ``35 mil 529``, ``13mil500``."""
    m = re.search(
        r"(-?\d+(?:\.\d+)?)\s*mil\s*(\d{1,3})?",
        s,
        flags=re.I,
    )
    if not m:
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*mil\b", s, flags=re.I)
        if not m:
            return None
        base = float(m.group(1)) * 1000.0
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            base += float(m.group(2))
        return base
    base = float(m.group(1)) * 1000.0
    if m.group(2):
        base += float(m.group(2))
    return base


def _parse_spanish_words_amount(s: str) -> Optional[float]:
    """Parser limitado para frases tipo ``trece mil quinientos veintinueve``."""
    low = re.sub(r"\s+", " ", s.lower().strip())
    if not low or re.search(r"\d", low):
        return None
    tokens = [t for t in re.split(r"\s+", low) if t]
    if not tokens:
        return None
    total = 0.0
    current = 0.0
    for tok in tokens:
        if tok not in _NUM_WORDS:
            return None
        val = float(_NUM_WORDS[tok])
        if val == 1000:
            current = (current or 1.0) * 1000.0
        elif val == 1_000_000:
            current = (current or 1.0) * 1_000_000.0
        elif val >= 100:
            current = (current + val) if current else val
        else:
            current += val
    total += current
    return total if total > 0 else None


def normalize_conversational_price(raw: str) -> Tuple[Optional[str], Optional[str], float]:
    """
    Devuelve ``(valor_canonico_str, error, confianza 0-1)``.

    - confianza >= 0.9: persistir directo
    - confianza < 0.9: pedir confirmación al chatbot
    """
    if not (raw or "").strip():
        return None, "vacío", 0.0

    s = _strip_noise(raw)
    low = s.lower()
    if low in ("n/a", "na", "pendiente", "—", "-"):
        return None, "usa número o 0", 0.0

    if re.match(r"^-?\d+(?:\.\d+)?$", s):
        try:
            v = float(s)
            if v != v:
                return None, "no es un número válido", 0.0
            return f"{v:g}", None, 1.0
        except ValueError:
            return None, "no es un número válido", 0.0

    mil_val = _parse_mil_pattern(s)
    if mil_val is not None:
        return f"{mil_val:g}", None, 0.95

    word_val = _parse_spanish_words_amount(s)
    if word_val is not None:
        return f"{word_val:g}", None, 0.85

    m = re.search(r"(-?\d[\d,]*(?:\.\d+)?)", s)
    if m:
        try:
            v = float(m.group(1).replace(",", ""))
            return f"{v:g}", None, 0.75
        except ValueError:
            pass

    return None, "no es un número válido", 0.0


_REFERENCE_RE = re.compile(
    r"(?i)^(?:igual\s+que|mismo\s+que|misma\s+que|como\s+(?:la|el|en)?)\s+(.+)$"
)


def resolve_price_reference(
    raw: str,
    economic_user_inputs: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str], float]:
    """
    Resuelve referencias tipo «igual que zona B» contra precios ya capturados.
    """
    text = (raw or "").strip()
    m = _REFERENCE_RE.match(text)
    if not m:
        return None, None, 0.0
    ref = re.sub(r"\s+", " ", m.group(1).strip().lower())
    inputs = economic_user_inputs if isinstance(economic_user_inputs, dict) else {}
    best_val: Optional[str] = None
    best_score = 0
    for key, val in inputs.items():
        if str(key).startswith("_"):
            continue
        key_norm = re.sub(r"\s+", " ", str(key).lower())
        score = 0
        if ref == key_norm:
            score = 3
        elif ref in key_norm or key_norm in ref:
            score = 2
        elif any(tok in key_norm for tok in ref.split() if len(tok) > 2):
            score = 1
        if score > best_score:
            try:
                best_val = f"{float(val):g}"
                best_score = score
            except (TypeError, ValueError):
                continue
    if best_val and best_score > 0:
        return best_val, None, 0.92
    return None, f"No encontré un precio previo para «{m.group(1).strip()}».", 0.0


def format_price_confirmation(label: str, canonical: str) -> str:
    """Eco humano antes de avanzar (confianza media)."""
    try:
        display = f"${float(canonical):,.2f}"
    except ValueError:
        display = canonical
    return (
        f"Interpreté **{display}** para **{label}**. "
        f"¿Es correcto? Responde **sí** para confirmar o escribe el monto de nuevo."
    )
