"""
Extracción determinista de identidad fiscal para persona física (INE + CIF SAT).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from app.services.legal_representative_parser import (
    _normalize_spaces,
    _rfc_prefix_letter_len,
    detect_cif_contribuyente_name,
    is_plausible_representative_name,
)

_INE_DOC_MARKERS = re.compile(
    r"instituto\s+nacional\s+electoral|credencial\s+para\s+votar|clave\s+de\s+elector|"
    r"m[eé]xico\s+instituto|identificaci[oó]n\s+oficial",
    re.IGNORECASE,
)

_RFC_FISICA_RE = re.compile(r"\b([A-ZÑ&]{4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE)

_INE_NOMBRE = re.compile(
    r"NOMBRE\s*(?:[:\n]\s*|\s+)"
    r"(?P<nom>[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\.]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\.]+){1,5})"
    r"(?=\s*(?:\n|DOMICILIO|SEXO|CURP|FECHA|CLAVE|INSTITUTO|VIGENCIA|EMISI)|\Z)",
    re.MULTILINE | re.IGNORECASE,
)


def is_ine_credential_text(text: str, max_scan_chars: int = 8000) -> bool:
    """True si el texto parece OCR de INE / identificación oficial."""
    clean = _normalize_spaces(text or "")
    if not clean:
        return False
    return bool(_INE_DOC_MARKERS.search(clean[:max_scan_chars]))


def detect_ine_holder_name(text: str) -> Dict[str, Any]:
    """Nombre del titular desde etiqueta NOMBRE típica de credencial INE."""
    raw = (text or "").strip()
    if not raw or not _INE_DOC_MARKERS.search(raw[:8000]):
        return _empty_name_result()

    m = _INE_NOMBRE.search(raw)
    if not m:
        m = _INE_NOMBRE.search(_normalize_spaces(raw))
    if not m:
        return _empty_name_result()

    full_name = _normalize_spaces(m.group("nom"))
    if not is_plausible_representative_name(full_name):
        return _empty_name_result()

    return {
        "found": True,
        "full_name": full_name,
        "confidence": 0.92,
        "strategy": "ine_nombre_label",
        "evidence": _normalize_spaces(m.group(0))[:320],
        "trigger": "ine_nombre",
    }


def _empty_name_result() -> Dict[str, Any]:
    return {
        "found": False,
        "full_name": None,
        "confidence": 0.0,
        "strategy": "ine_nombre_label",
        "evidence": "",
        "trigger": "none",
    }


def _score_rfc_fisica_local_context(upper_text: str, start: int, end: int) -> int:
    """RFC de persona física cerca de etiquetas INE / CIF física."""
    lo = max(0, start - 260)
    hi = min(len(upper_text), end + 260)
    w = upper_text[lo:hi].lower()
    score = 0
    positives = (
        "nombre (s)",
        "nombre(s)",
        "primer apellido",
        "segundo apellido",
        "curp",
        "persona fisica",
        "persona física",
        "contribuyente",
        "rfc:",
        " rfc ",
        "registro federal",
        "cedula de identificacion fiscal",
        "constancia de situacion",
        "instituto nacional electoral",
        "credencial para votar",
    )
    negatives = (
        "razon social",
        "razón social",
        "denominacion",
        "denominación",
        "sociedad anonima",
        "s.a. de c.v",
        "persona moral",
        "regimen capital",
    )
    for p in positives:
        if p in w:
            score += 14
    for n in negatives:
        if n in w:
            score -= 12
    return score


def resolve_rfc_persona_fisica(text: str, llm_rfc: Optional[str]) -> Dict[str, Any]:
    """
    Selecciona RFC de persona física (4 letras iniciales) cuando el texto mezcla RFC moral.
    """
    clean = _normalize_spaces(text or "")
    placeholders = {"", "NO ENCONTRADO", "NO ENCONTRADO.", "N/A", "...", "S/D", "SD"}

    if not clean:
        return {
            "value": None,
            "strategy": "empty_context",
            "previous_llm": llm_rfc,
            "evidence_snippet": "",
            "changed": False,
        }

    upper = clean.upper()
    by_rfc: Dict[str, Tuple[int, int, int]] = {}
    for m in _RFC_FISICA_RE.finditer(upper):
        val = m.group(1).upper()
        if _rfc_prefix_letter_len(val) != 4:
            continue
        sc = _score_rfc_fisica_local_context(upper, m.start(), m.end())
        prev = by_rfc.get(val)
        if prev is None or sc > prev[2] or (sc == prev[2] and m.start() < prev[0]):
            by_rfc[val] = (m.start(), m.end(), sc)

    llm_u = (llm_rfc or "").strip().upper()
    llm_norm = llm_u if llm_u not in placeholders else ""

    if not by_rfc:
        return {
            "value": llm_norm or None,
            "strategy": "llm_no_fisica_rfc_pattern_in_text",
            "previous_llm": llm_rfc,
            "evidence_snippet": clean[:280],
            "changed": False,
        }

    ranked = sorted(by_rfc.items(), key=lambda kv: (-kv[1][2], kv[1][0]))
    best_rfc, (s, e, _) = ranked[0]
    evidence = clean[max(0, s - 40) : min(len(clean), e + 80)].strip()

    if not llm_norm:
        return {
            "value": best_rfc,
            "strategy": "deterministic_fisica_rfc_anchor",
            "previous_llm": llm_rfc,
            "evidence_snippet": evidence[:320],
            "changed": bool(llm_rfc),
        }

    llm_prefix = _rfc_prefix_letter_len(llm_norm)
    if llm_prefix == 3:
        return {
            "value": best_rfc,
            "strategy": "deterministic_fisica_rfc_anchor_over_moral_llm",
            "previous_llm": llm_rfc,
            "evidence_snippet": evidence[:320],
            "changed": llm_norm != best_rfc,
        }

    if llm_prefix == 4 and llm_norm in by_rfc:
        s2, e2, _ = by_rfc[llm_norm]
        ev2 = clean[max(0, s2 - 40) : min(len(clean), e2 + 80)].strip()
        return {
            "value": llm_norm,
            "strategy": "llm_fisica_rfc_confirmed_in_text",
            "previous_llm": llm_rfc,
            "evidence_snippet": ev2[:320],
            "changed": False,
        }

    return {
        "value": best_rfc,
        "strategy": "deterministic_fisica_rfc_anchor",
        "previous_llm": llm_rfc,
        "evidence_snippet": evidence[:320],
        "changed": llm_norm != best_rfc,
    }


def resolve_fisica_full_name(
    *,
    ine_blob: str,
    cif_blob: str,
    fallback_blob: str = "",
) -> Dict[str, Any]:
    """Precedencia: INE > CIF SAT > vacío."""
    for blob, detector in (
        (ine_blob, detect_ine_holder_name),
        (cif_blob, detect_cif_contribuyente_name),
        (fallback_blob, detect_ine_holder_name),
        (fallback_blob, detect_cif_contribuyente_name),
    ):
        text = (blob or "").strip()
        if len(text) < 20:
            continue
        hit = detector(text)
        if hit.get("found") and hit.get("full_name"):
            return hit
    return _empty_name_result()
