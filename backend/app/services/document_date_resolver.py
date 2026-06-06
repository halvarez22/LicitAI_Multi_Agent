"""
Resuelve la fecha a imprimir en documentos de propuesta (universal, sin hardcode por licitación).

Cascada: override usuario > cronograma (presentación de proposiciones) > fecha sistema acotada al hito.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

_DATE_ES_BODY_REPLACE_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+("
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
    r")\s+de\s+(\d{4})\b",
    re.IGNORECASE,
)

from app.agents.analyst import normalize_cronograma_dict
from app.config.settings import settings
from app.services.cronograma_bases_extract import parse_spanish_date_fragment

_MESES_ES_OUT = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _subtract_business_days(dt: datetime, days: int) -> datetime:
    if days <= 0:
        return dt
    cur = dt
    remaining = days
    while remaining > 0:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            remaining -= 1
    return cur


def _format_fecha_es(dt: datetime) -> str:
    return f"{dt.day} de {_MESES_ES_OUT[dt.month - 1]} de {dt.year}"


def _format_fecha_corta(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y")


def _cronograma_from_session(session_state: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(session_state, dict):
        return normalize_cronograma_dict({})
    for container_key in ("last_analysis", "analysis_snapshot"):
        raw = session_state.get(container_key)
        if isinstance(raw, dict) and raw.get("cronograma"):
            return normalize_cronograma_dict(raw.get("cronograma"))
    er = session_state.get("execution_results")
    if isinstance(er, dict):
        for step in ("analyst", "compliance", "datagap"):
            block = er.get(step)
            if isinstance(block, dict):
                data = block.get("data") if isinstance(block.get("data"), dict) else block
                if isinstance(data, dict) and data.get("cronograma"):
                    return normalize_cronograma_dict(data.get("cronograma"))
    return normalize_cronograma_dict(session_state.get("cronograma"))


def resolve_document_date(
    session_state: Optional[Dict[str, Any]] = None,
    *,
    user_override: Optional[str] = None,
    hito_key: str = "presentacion_proposiciones",
) -> Dict[str, Any]:
    """
    Devuelve fecha canónica para documentos.

    Returns:
        dict con ``fecha_es``, ``fecha_corta``, ``source``, ``deadline_raw``,
        ``deadline_dt`` (iso o None), ``is_after_deadline``.
    """
    if user_override and str(user_override).strip():
        parsed = parse_spanish_date_fragment(str(user_override))
        if parsed:
            return {
                "fecha_es": _format_fecha_es(parsed),
                "fecha_corta": _format_fecha_corta(parsed),
                "source": "user_override",
                "deadline_raw": "",
                "deadline_dt": None,
                "is_after_deadline": False,
            }

    cronograma = _cronograma_from_session(session_state or {})
    bases_blob = ""
    if isinstance(session_state, dict):
        bases_blob = str(session_state.get("bases_corpus_hint") or "").strip()
    if bases_blob:
        from app.services.cronograma_bases_extract import merge_cronograma_with_bases

        cronograma = merge_cronograma_with_bases(cronograma, bases_blob)
    deadline_raw = str(cronograma.get(hito_key) or cronograma.get("recepcion_proposiciones") or "").strip()
    deadline_dt = parse_spanish_date_fragment(deadline_raw) if deadline_raw else None

    offset = int(getattr(settings, "DOCUMENT_DATE_OFFSET_BUSINESS_DAYS", 2) or 2)
    if deadline_dt:
        doc_dt = _subtract_business_days(deadline_dt, offset)
        now = datetime.now()
        if doc_dt.date() > deadline_dt.date():
            doc_dt = _subtract_business_days(deadline_dt, 1)
        # Si la generación ocurre después del cierre, conservar fecha lógica previa al hito.
        if now.date() <= deadline_dt.date() and doc_dt.date() > now.date():
            doc_dt = now
        is_late = now.date() > deadline_dt.date()
        return {
            "fecha_es": _format_fecha_es(doc_dt),
            "fecha_corta": _format_fecha_corta(doc_dt),
            "source": f"cronograma:{hito_key}",
            "deadline_raw": deadline_raw,
            "deadline_dt": deadline_dt.isoformat(),
            "is_after_deadline": is_late,
        }

    now = datetime.now()
    return {
        "fecha_es": _format_fecha_es(now),
        "fecha_corta": _format_fecha_corta(now),
        "source": "system_fallback",
        "deadline_raw": "",
        "deadline_dt": None,
        "is_after_deadline": False,
    }


def normalize_body_spanish_dates(text: str, canonical_fecha_es: str) -> str:
    """
    Unifica fechas literales en el cuerpo a la fecha canónica del expediente.

    Evita que el LLM inserte la fecha del servidor (p. ej. junio) en TE-01 u otros DOCX.
    """
    canon = str(canonical_fecha_es or "").strip()
    if not canon or not text:
        return text
    canon_key = re.sub(r"\s+", " ", canon.lower())

    def _repl(match: re.Match[str]) -> str:
        frag = re.sub(r"\s+", " ", match.group(0).strip().lower())
        if frag == canon_key:
            return match.group(0)
        return canon

    return _DATE_ES_BODY_REPLACE_RE.sub(_repl, text)


def resolve_addressee_lines(
    session_state: Optional[Dict[str, Any]] = None,
    triage_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Destinatario de cartas: convocante de triage/análisis o genérico."""
    tc = triage_context if isinstance(triage_context, dict) else {}
    conv = str(tc.get("convocante") or tc.get("autoridad_convocante") or "").strip()
    if not conv and isinstance(session_state, dict):
        for key in ("last_analysis", "analysis_snapshot"):
            block = session_state.get(key)
            if isinstance(block, dict):
                conv = str(
                    block.get("convocante")
                    or block.get("autoridad_convocante")
                    or block.get("entidad")
                    or ""
                ).strip()
                if conv:
                    break
    if conv:
        return f"{conv.upper()}\nPRESENTE.-"
    return "A QUIEN CORRESPONDA:"
