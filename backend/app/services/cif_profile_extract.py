"""
Extracción determinista de datos fiscales desde texto OCR de CIF / constancia SAT.

Complementa al LLM en ``analyze_company``: domicilio fiscal y razón social moral
cuando las etiquetas del formato SAT son reconocibles pese a ruido de OCR.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _field_line(text: str, pattern: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    return re.sub(r"\s+", " ", (m.group(1) or "").strip())


def _extract_moderno_domicilio(text: str) -> Optional[str]:
    """Constancia tipo SAT con vialidad, colonia, CP, municipio y entidad."""
    parts: list[str] = []
    calle = _field_line(text, r"Nombre\s+de\s+vialidad\s*[:\s]+\s*([^\n\r]+)")
    if not calle:
        calle = _field_line(text, r"(?:Calle|C\.)\s*[:\s]+\s*([^\n\r]+)")
    num_ext = _field_line(text, r"N[uú]mero\s+exterior\s*[:\s]+\s*([^\n\r]+)")
    num_int = _field_line(text, r"N[uú]mero\s+interior\s*[:\s]+\s*([^\n\r]+)")
    col = _field_line(text, r"Nombre\s+de\s+la\s+colonia\s*[:\s]+\s*([^\n\r]+)")
    cp = _field_line(text, r"C[oó]digo\s+postal\s*[:\s]+\s*(\d{5})\b")
    loc = _field_line(text, r"Nombre\s+de\s+la\s+localidad\s*[:\s]+\s*([^\n\r]+)")
    mun = _field_line(text, r"Nombre\s+del\s+municipio[^\n\r]*?\s*[:\s]+\s*([^\n\r]+)")
    ent = _field_line(text, r"Nombre\s+de\s+la\s+entidad\s+federativa\s*[:\s]+\s*([^\n\r]+)")

    for p in (calle, num_ext, num_int, col, cp, loc, mun, ent):
        v = (p or "").strip()
        if not v:
            continue
        if v.upper() in {"S/N", "-", "N/A", "SN", "NA"}:
            continue
        parts.append(v)
    if len(parts) >= 2:
        joined = ", ".join(parts)
        if len(joined) >= 12:
            return joined
    return None


def _extract_legacy_domicilio_fiscal(text: str) -> Optional[str]:
    m = re.search(
        r"(?is)\bdomicilio\s+fiscal\s*[:\n]\s*(?P<d>.+?)(?=\n\s*(?:r[eé]gimen|actividad\s+econ"
        r"|r\.?\s*f\.?\s*c\.?\b|clave\s+en\s+el\s+catastro|fecha\s+de\s+emis)|\Z)",
        text,
    )
    if not m:
        return None
    d = re.sub(r"\s+", " ", m.group("d")).strip()
    if len(d) >= 12:
        return d
    return None


def _extract_razon_social_moral(text: str) -> Optional[str]:
    """Denominación en constancia persona moral (evita bloque Nombre(s) de persona física)."""
    m = re.search(
        r"(?is)"
        r"(?:nombre,?\s*denominaci[oó]n\s+o\s+raz[oó]n\s+social|denominaci[oó]n\s+social)\s*[:]?\s*"
        r"(?:\n\s*|\s+)"
        r"(?P<rz>[^\n\r]{4,220}?)"
        r"(?=\s*(?:\n|$))",
        text,
    )
    if not m:
        return None
    rz = re.sub(r"\s+", " ", m.group("rz")).strip()
    if len(rz) >= 4 and not re.match(r"^(nombre|primer|segundo)\s*\(", rz, re.I):
        return rz
    return None


def extract_cif_company_profile_patch(cif_blob: str, is_fisica: bool) -> Dict[str, Any]:
    """
    Analiza texto acumulado de documentos CIF/constancia y devuelve campos detectables.

    Args:
        cif_blob: Texto OCR concatenado de uno o más PDF tipo constancia.
        is_fisica: True si la empresa es persona física (no rellena razón social moral).

    Returns:
        Dict con claves opcionales ``domicilio_fiscal``, ``razon_social``,
        metadatos ``_cif_extract_strategy`` para depuración.
    """
    raw = (cif_blob or "").strip()
    out: Dict[str, Any] = {}
    if len(raw) < 40:
        return out

    strategies: list[str] = []

    dom = _extract_moderno_domicilio(raw)
    if dom:
        strategies.append("domicilio_moderno_sat")
    else:
        dom = _extract_legacy_domicilio_fiscal(raw)
        if dom:
            strategies.append("domicilio_legacy_bloque")

    if dom:
        out["domicilio_fiscal"] = dom

    if not is_fisica:
        rz = _extract_razon_social_moral(raw)
        if rz:
            out["razon_social"] = rz
            strategies.append("razon_social_denominacion_cif")

    if strategies:
        out["_cif_extract_strategy"] = "+".join(strategies)
    return out
