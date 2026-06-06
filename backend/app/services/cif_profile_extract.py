"""
Extracción determinista de datos fiscales desde texto OCR de CIF / constancia SAT.

Complementa al LLM en ``analyze_company``: domicilio fiscal y razón social moral
cuando las etiquetas del formato SAT son reconocibles pese a ruido de OCR.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _clean_field_value(raw: str) -> str:
    """Limpia valor OCR: tablas markdown SAT, pipes y etiquetas pegadas en la misma línea."""
    v = re.sub(r"\s+", " ", (raw or "").strip())
    if not v:
        return ""
    if "|" in v:
        v = v.split("|", 1)[0].strip()
    v = re.split(
        r"\s+(?:N[uú]mero\s+(?:exterior|interior)|Nombre\s+de\s+(?:la\s+)?(?:colonia|localidad|vialidad)|"
        r"C[oó]digo\s+postal|Tipo\s+de\s+vialidad|Entre\s+calle|Y\s+calle|Correo\s+electr[oó]nico)\s*:",
        v,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    v = re.sub(
        r"^(?:o\s+)?demarcaci[oó]n\s+territorial\s*:\s*",
        "",
        v,
        flags=re.IGNORECASE,
    ).strip()
    return v


def _field_line(text: str, pattern: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    return _clean_field_value(m.group(1) or "")


def _extract_moderno_domicilio(text: str) -> Optional[str]:
    """Constancia tipo SAT con vialidad, colonia, CP, municipio y entidad."""
    parts: list[str] = []
    calle = _field_line(text, r"Nombre\s+de\s+[Vv]ialidad\s*[:\s]+\s*([^\n\r|]+)")
    if not calle:
        calle = _field_line(text, r"(?:Calle|C\.)\s*[:\s]+\s*([^\n\r|]+)")
    num_ext = _field_line(text, r"N[uú]mero\s+[Ee]xterior\s*[:\s]+\s*([^\n\r|]+)")
    num_int = _field_line(text, r"N[uú]mero\s+[Ii]nterior\s*[:\s]+\s*([^\n\r|]+)")
    col = _field_line(text, r"Nombre\s+de\s+la\s+[Cc]olonia\s*[:\s]+\s*([^\n\r|]+)")
    cp = _field_line(text, r"C[oó]digo\s+[Pp]ostal\s*[:\s]*(\d{5})\b")
    loc = _field_line(text, r"Nombre\s+de\s+la\s+[Ll]ocalidad\s*[:\s]+\s*([^\n\r|]+)")
    mun = _field_line(
        text,
        r"Nombre\s+del\s+[Mm]unicipio(?:\s+o\s+[Dd]emarcaci[oó]n\s+[Tt]erritorial)?\s*[:\s]+\s*([^\n\r|]+)",
    )
    ent = _field_line(text, r"Nombre\s+de\s+la\s+[Ee]ntidad\s+[Ff]ederativa\s*[:\s]+\s*([^\n\r|]+)")

    street_parts: list[str] = []
    if calle:
        street_parts.append(calle)
    if num_ext:
        street_parts.append(num_ext)
    if num_int and num_int.upper() not in {"S/N", "-", "N/A", "SN", "NA"}:
        street_parts[-1:] = [f"{street_parts[-1]}-{num_int}" if street_parts else num_int]

    locality_parts: list[str] = []
    for p in (col, cp, loc, mun, ent):
        v = (p or "").strip()
        if not v:
            continue
        if v.upper() in {"S/N", "-", "N/A", "SN", "NA"}:
            continue
        locality_parts.append(v)

    parts = street_parts + locality_parts
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
        r"(?is)Denominaci[oó]n\s*/?\s*Raz[oó]n\s+Social\s*:?\s*\|?\s*([^\n\r|]{4,220})",
        text,
    )
    if m:
        rz = _clean_field_value(m.group(1))
        if len(rz) >= 4 and not re.match(r"^(nombre|primer|segundo|id)\b", rz, re.I):
            return rz

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
    rz = _clean_field_value(m.group("rz"))
    if len(rz) >= 4 and not re.match(r"^(nombre|primer|segundo|id)\b", rz, re.I):
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
