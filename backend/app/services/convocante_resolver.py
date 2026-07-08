"""
Resolución universal de convocante / destinatario de cartas desde corpus o sesión.

Sin hardcode por licitación: patrones de encabezado de bases, triage y análisis.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, List

_AYUNTAMIENTO_RE = re.compile(
    r"(?im)^\s*(H\.\s*AYUNTAMIENTO\s+[^\n]{4,120})$",
)
_DIRECCION_GENERAL_RE = re.compile(
    r"(?im)^\s*((?:DIRECCI[OÓ]N|DIR\.)\s+GENERAL\s+[^\n]{4,100})$",
)
_COMITE_RE = re.compile(
    r"(?im)(COMIT[EÉ]\s+DE\s+(?:ADQUISICIONES|CONTRATACI[OÓ]N|EVALUACI[OÓ]N)[^\n\.]{0,120})",
)
_SECRETARIA_RE = re.compile(
    r"(?im)^\s*(SECRETAR[IÍ]A\s+(?:DE\s+)?[^\n]{6,120})$",
)
_LICITACION_NUM_RE = re.compile(
    r"(?i)(LICITACI[OÓ]N\s+P[UÚ]BLICA\s+(?:N[UÚ]M\.?|NO\.?|N[O°]\.?)\s*"
    r"[A-Z0-9][A-Z0-9/\-\.]{2,40})",
)
_INSTITUCION_RE = re.compile(
    r"(?im)^\s*((?:UNIVERSIDAD|INSTITUTO|HOSPITAL|COMISI[OÓ]N|ORGANISMO|"
    r"DEPENDENCIA|SUBSECRETAR[IÍ]A)[^\n]{6,120})$",
)


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip(" .;,-"))


def extract_convocante_from_text(text: str, *, max_scan: int = 120_000) -> Dict[str, str]:
    """
    Extrae convocante, dependencia y número de licitación del encabezado de bases.

    Returns:
        Dict con claves opcionales: convocante, autoridad_convocante, comite,
        concurso_label, destinatario, entidad, dependencia.
    """
    blob = str(text or "")[:max_scan]
    if not blob.strip():
        return {}

    out: Dict[str, str] = {}
    ayto = ""
    m_ay = _AYUNTAMIENTO_RE.search(blob)
    if m_ay:
        ayto = _clean_line(m_ay.group(1))

    dep = ""
    m_dep = _DIRECCION_GENERAL_RE.search(blob)
    if m_dep:
        dep = _clean_line(m_dep.group(1))

    comite = ""
    m_com = _COMITE_RE.search(blob)
    if m_com:
        comite = _clean_line(m_com.group(1))

    sec = ""
    m_sec = _SECRETARIA_RE.search(blob)
    if m_sec:
        sec = _clean_line(m_sec.group(1))

    inst = ""
    for m_inst in _INSTITUCION_RE.finditer(blob):
        cand = _clean_line(m_inst.group(1))
        if len(cand) > 12:
            inst = cand
            break

    proc = ""
    m_proc = _LICITACION_NUM_RE.search(blob)
    if m_proc:
        proc = _clean_line(m_proc.group(1))

    # Jerarquía destinatario
    lines: list[str] = []
    if comite:
        lines.append(comite.upper())
    else:
        if ayto:
            lines.append(ayto.upper())
        if dep:
            lines.append(dep.upper())
        if sec and sec.upper() not in {x.upper() for x in lines}:
            lines.append(sec.upper())
        if inst and not lines:
            lines.append(inst.upper())

    convocante = ""
    if ayto and dep:
        convocante = f"{ayto} — {dep}"
    elif ayto:
        convocante = ayto
    elif dep:
        convocante = dep
    elif sec:
        convocante = sec
    elif inst:
        convocante = inst
    elif comite:
        convocante = comite

    if convocante:
        out["convocante"] = convocante
        out["autoridad_convocante"] = convocante
    if ayto:
        out["entidad"] = ayto
    if dep:
        out["dependencia"] = dep
    if comite:
        out["comite"] = comite
    if proc:
        out["concurso_label"] = proc

    if lines:
        if comite:
            out["destinatario"] = f"{lines[0]}\nP R E S E N T E"
        else:
            out["destinatario"] = "\n".join(lines) + "\nPRESENTE.-"
    lugar = city_from_convocante_text(blob)
    if lugar:
        out["lugar_convocante"] = lugar
    return out


def fetch_convocante_header_from_index(session_id: str) -> str:
    """
    Recupera encabezados de convocante desde el índice de bases (HRU).

    Complementa ``bases_corpus_hint`` cuando el snippet del requisito es estrecho.
    """
    if not str(session_id or "").strip():
        return ""
    from app.services.vector_service import VectorDbServiceClient

    vdb = VectorDbServiceClient()
    parts: List[str] = []
    seen: set = set()
    queries = (
        "H AYUNTAMIENTO MUNICIPIO DE DIRECTOR GENERAL OBRA PUBLICA PRESENTE",
        "COMITE DE ADQUISICIONES CONTRATACION PRESENTE",
        "LICITACION PUBLICA NUM DIRECTOR GENERAL",
        "SECRETARIA DE DEPENDENCIA CONVOCANTE",
    )

    def _add(text: str) -> None:
        t = str(text or "").strip()
        if not t or t in seen:
            return
        low = t.lower()
        if not any(
            k in low
            for k in (
                "ayuntamiento",
                "director general",
                "comité",
                "comite",
                "secretaría",
                "secretaria",
                "presente",
            )
        ):
            return
        seen.add(t)
        parts.append(t)

    for q in queries:
        try:
            res = vdb.query_texts(session_id, q, n_results=12)
            for doc in res.get("documents") or []:
                _add(str(doc or ""))
        except Exception:
            continue
    return "\n\n".join(parts)[:80000]


def city_from_convocante_text(text: str) -> str:
    """
    Extrae municipio/ciudad de la sede convocante (Ayuntamiento, Municipio, etc.).

    Universal: no fija entidades; usa patrones de encabezado de bases.
    """
    blob = str(text or "")[:8000]
    if not blob.strip():
        return ""

    m_pair = re.search(
        r"(?i)(?:H\.\s*)?(?:AYUNTAMIENTO|MUNICIPIO)\s+DE\s+([^,\n]{3,80})\s*,\s*"
        r"([A-ZÁÉÍÓÚÑ\.]{2,12})",
        blob,
    )
    if m_pair:
        city = _clean_line(m_pair.group(1))
        state = _clean_line(m_pair.group(2)).replace(".", "")
        if city:
            return f"{city}, {state}" if state else city

    m_city = re.search(
        r"(?i)(?:H\.\s*)?(?:AYUNTAMIENTO|MUNICIPIO)\s+DE\s+([^,\n]{3,80})",
        blob,
    )
    if m_city:
        return _clean_line(m_city.group(1))

    m_inst = re.search(
        r"(?i)\b(?:CIUDAD|LOCALIDAD|MUNICIPIO)\s*[:\-]\s*([^\n,;]{3,80})",
        blob,
    )
    if m_inst:
        cand = _clean_line(m_inst.group(1))
        if cand and not re.search(r"(?i)c[oó]digo\s+postal|\bcp\b", cand):
            return cand
    return ""


def merge_convocante_into_session_patch(
    session_state: Optional[Dict[str, Any]],
    corpus_text: str = "",
) -> Dict[str, Any]:
    """
    Devuelve parches para sesión/last_analysis si el corpus aporta convocante nuevo.
    """
    session_state = session_state or {}
    existing = ""
    for key in ("last_analysis", "analysis_snapshot"):
        block = session_state.get(key)
        if isinstance(block, dict):
            existing = str(block.get("convocante") or block.get("autoridad_convocante") or "")
            if existing.strip():
                break
    if not existing.strip():
        existing = str(session_state.get("convocante") or "")

    hints = [
        corpus_text,
        str(session_state.get("bases_corpus_hint") or ""),
    ]
    for key in ("last_analysis", "analysis_snapshot"):
        block = session_state.get(key)
        if isinstance(block, dict):
            hints.append(str(block.get("alcance_operativo") or ""))
            hints.append(str(block.get("objeto") or ""))

    extracted: Dict[str, str] = {}
    for hint in hints:
        if not hint or len(hint.strip()) < 80:
            continue
        found = extract_convocante_from_text(hint)
        if found.get("convocante"):
            extracted = found
            break

    if not extracted.get("convocante"):
        return {}

    if existing.strip() and len(existing) >= len(extracted["convocante"]) - 5:
        return {}

    patch: Dict[str, Any] = {"convocante": extracted["convocante"]}
    for k in ("autoridad_convocante", "entidad", "dependencia", "comite", "concurso_label", "destinatario"):
        if extracted.get(k):
            patch[k] = extracted[k]
    return patch


def enrich_analysis_with_convocante(
    extracted_data: Dict[str, Any],
    context_text: str,
) -> Dict[str, Any]:
    """Enriquece salida del analista con convocante detectado en el contexto de bases."""
    if not isinstance(extracted_data, dict):
        return extracted_data
    found = extract_convocante_from_text(context_text)
    if not found.get("convocante"):
        return extracted_data
    for k, v in found.items():
        if v and not str(extracted_data.get(k) or "").strip():
            extracted_data[k] = v
    return extracted_data
