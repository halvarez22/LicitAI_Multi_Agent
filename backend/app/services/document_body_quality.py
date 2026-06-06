"""
Métricas universales de cuerpo sustantivo en texto legal (markdown o DOCX plano).

Detecta «cascarones»: solo membrete, LUGAR Y FECHA y firma sin declaración/manifiesto.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from app.config.settings import settings

# Líneas estructurales que _save_docx añade y no cuentan como cuerpo legal.
_STRUCTURE_LINE_RE = re.compile(
    r"(?i)^("
    r"panel[_\s]|lugares?\s+y\s+fecha|a\s+quien\s+corresponde|presente\.?-?"
    r"|_{5,}|a\s+t\s+e\s+n\s+t\s+a\s+m\s+e\s+n\s+t\s+e"
    r"|representante\s+legal|r\.?f\.?c\.?"
    r")"
)

_LEGAL_MARKER_RE = re.compile(
    r"(?i)\b("
    r"protesta\s+de\s+decir\s+verdad|manifiesto|declaro|el\s+suscrito|"
    r"quien\s+suscribe|mi\s+representada|bajo\s+protesta|"
    r"por\s+medio\s+de\s+la\s+presente|nos\s+comprometemos"
    r")\b"
)

_PANEL_LEAK_RE = re.compile(r"(?i)panel[_\|]")

# Anexos técnicos operativos (matrices, partidas, actividades): espejo del pliego, no manifiesto legal.
_OPERATIONAL_TECH_FORM_RE = re.compile(
    r"(?i)(anexo\s*iii|actividades\s+del\s+supervisor|supervisor\s+de\s+limp|"
    r"partida\s*\d|entrega\s+de\s+material|cronograma|matriz|programa\s+de\s+trabajo|"
    r"metodolog|plan\s+de\s+trabajo|descripcion\s+de\s+actividades)"
)


def is_operational_technical_form_document(basename: str) -> bool:
    """
    True si el archivo es un formato operativo del convocante (tablas/partidas),
    no una carta o declaración con cuerpo legal sustantivo.
    """
    blob = str(basename or "").replace("_", " ")
    return bool(_OPERATIONAL_TECH_FORM_RE.search(blob))


_CONVOCANTE_TEMPLATE_ARTIFACT_RE = re.compile(
    r"(?i)(^mirror_|^cat[_\s]anexo|^panel[_\s]pliego|modelo\s+contrato\s+federal|"
    r"formato\s+entrega\s+de\s+preguntas|constancia\s+de\s+visitas|"
    r"descripcion\s+del\s+servicio\s+de\s+limp|dc[\s\-]*4|lista\s+de\s+constancias)"
)


def is_convocante_template_artifact(basename: str) -> bool:
    """
    Espejo o copia fiel de plantilla del pliego/catálogo (no redacción LLM del licitante).

    En estos archivos es normal: siglas de hospital (CEYE, CINCO), criterios de evaluación
    citados del contrato federal, fechas de vigencia del servicio, y campos en blanco del formato.
    """
    raw = str(basename or "")
    blob = raw.replace("_", " ")
    if is_operational_technical_form_document(raw):
        return True
    return bool(_CONVOCANTE_TEMPLATE_ARTIFACT_RE.search(blob) or _CONVOCANTE_TEMPLATE_ARTIFACT_RE.search(raw))


def should_relax_fill_quality_gate(basename: str, *, stage: str) -> bool:
    """True si el gate de llenado no debe exigir carta/manifiesto ni léxico de postura."""
    if str(stage or "").strip().lower() not in ("technical", "formats"):
        return False
    return is_convocante_template_artifact(basename)


# Léxico heredado del pliego en espejos/catálogo: no bloquear entrega CompraNet.
TEMPLATE_CONTAMINATION_RELAXED_ERROR_TYPES = frozenset(
    {
        "adjudication_language_in_proposal_stage",
        "bases_checklist_in_letter_body",
        "evaluator_perspective_detected",
        "contract_language_in_proposal_stage",
        "document_date_after_submission_deadline",
        "document_multiple_dates_in_body",
        "generic_legal_fallback_body",
        "cross_tender_reference",
    }
)


def should_relax_delivery_contamination(basename: str) -> bool:
    """True si el archivo es plantilla espejo del convocante (auditoría P0 en empaquetado)."""
    return is_convocante_template_artifact(basename)


def _min_substantive_words() -> int:
    return int(getattr(settings, "DOCUMENT_MIN_SUBSTANTIVE_WORDS", 40) or 40)


def substantive_body_metrics(text: str) -> Dict[str, Any]:
    """
    Cuenta palabras útiles tras quitar líneas estructurales obvias.

    Returns:
        dict con word_count, has_legal_marker, is_shell, panel_leak.
    """
    raw = str(text or "").strip()
    if not raw:
        return {
            "word_count": 0,
            "has_legal_marker": False,
            "is_shell": True,
            "panel_leak": False,
        }

    panel_leak = bool(_PANEL_LEAK_RE.search(raw))
    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _STRUCTURE_LINE_RE.match(stripped):
            continue
        if re.fullmatch(r"[_\-\s|]+", stripped):
            continue
        kept.append(stripped)

    body = "\n".join(kept)
    words = re.findall(r"[a-záéíóúñü0-9]+", body.lower())
    word_count = len(words)
    has_legal = bool(_LEGAL_MARKER_RE.search(body))
    min_w = _min_substantive_words()
    is_shell = word_count < min_w and not has_legal

    return {
        "word_count": word_count,
        "has_legal_marker": has_legal,
        "is_shell": is_shell,
        "panel_leak": panel_leak,
    }


def is_substantive_markdown(text: str, *, require_legal_marker: bool | None = None) -> bool:
    """
    True si el markdown previo a _save_docx tiene cuerpo legal suficiente.

    Por defecto exige marcador de declaración/manifiesto (evita cascarones con relleno).
    """
    if require_legal_marker is None:
        require_legal_marker = bool(
            getattr(settings, "DOCUMENT_REQUIRE_LEGAL_MARKER", True)
        )
    m = substantive_body_metrics(text)
    if m.get("panel_leak"):
        return False
    if require_legal_marker and not m.get("has_legal_marker"):
        return False
    return not bool(m.get("is_shell"))


def scan_materialized_doc_text(
    text: str,
    *,
    basename: str = "",
) -> Dict[str, Any] | None:
    """
    Hit para gate post-materialización (DOCX ya guardado).

    Returns:
        dict error payload o None si OK.
    """
    if basename and is_operational_technical_form_document(basename):
        return None
    m = substantive_body_metrics(text)
    if m.get("panel_leak"):
        return {
            "error_type": "document_metadata_leak",
            "field_key": "content",
            "detected_value": "panel_administrativo",
            "expected_rule": "no_internal_panel_tokens_in_deliverable",
        }
    if m.get("is_shell"):
        return {
            "error_type": "document_shell_detected",
            "field_key": "content",
            "detected_value": f"words={m.get('word_count')}",
            "expected_rule": f"substantive_legal_body>={_min_substantive_words()}_words_or_protesta_marker",
        }
    return None
