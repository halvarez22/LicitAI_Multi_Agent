"""
Redacción universal para tickets de aclaración y preguntas de junta (audiencia: convocante).

Evita texto de chat interno («¿Deseas prepararlo…?») en salidas exportables.
Sin referencias a licitaciones, empresas ni anexos concretos.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Códigos técnicos → motivo legible (extensible por reason/error_type)
_REASON_LABELS_ES: Dict[str, str] = {
    "required_annex_not_published": (
        "no consta publicado en el expediente electrónico de la convocatoria"
    ),
    "embedded_in_bases_pdf": (
        "el formato aparece integrado en el PDF de bases y no como archivo suelto en el expediente"
    ),
    "missing_official_template": (
        "no se localiza la plantilla oficial en el expediente publicado"
    ),
    "template_ambiguous": (
        "las bases no precisan con claridad el contenido o alcance del formato"
    ),
    "clarification_required": (
        "existen dudas sobre cómo debe integrarse el documento en la proposición"
    ),
    "cross_tender_reference": (
        "el material disponible podría no corresponder a este procedimiento"
    ),
    "official_template_expected": (
        "se exige formato oficial sin versión publicada identificable"
    ),
    "coverage_blocked": (
        "no hay evidencia de cumplimiento documental en el expediente del licitante"
    ),
    "not_applicable": "su aplicabilidad al procedimiento no está clara",
}

_INTERNAL_TICKET_DRAFT_RE = re.compile(
    r"(?i)necesito aclarar con la convocante|motivo detectado\s*:|"
    r"¿\s*deseas prepararlo|prepararlo como punto para la junta|"
    r"escríbeme|pulsa\s+\*\*generar\*\*"
)

_JUNTA_CANONICAL_RE = re.compile(
    r"(?i)^\s*con respecto\b|solicitamos aclaración|¿cuál es el criterio oficial"
)


def _norm_reason_key(reason: str) -> str:
    key = re.sub(r"[^a-z0-9_]+", "_", str(reason or "").strip().lower())
    return re.sub(r"_+", "_", key).strip("_")


def humanize_clarification_reason(reason: str) -> str:
    """
    Traduce un código ``reason`` / ``error_type`` a motivo en español para la convocante.

    Si el código no está catalogado, convierte snake_case a frase legible.
    """
    key = _norm_reason_key(reason)
    if key in _REASON_LABELS_ES:
        return _REASON_LABELS_ES[key]
    if not key:
        return "no se cuenta con claridad sobre el requisito documental"
    words = key.replace("_", " ")
    return f"se detecta la situación: {words}"


def is_internal_ticket_draft(text: str) -> bool:
    """True si el texto es borrador de chat/HITL, no apto para junta ni portal."""
    return bool(_INTERNAL_TICKET_DRAFT_RE.search(str(text or "")))


def is_junta_canonical_question(text: str) -> bool:
    """True si ya está redactada en formato de pregunta a la convocante."""
    p = str(text or "").strip()
    return bool(p) and bool(_JUNTA_CANONICAL_RE.search(p))


def build_ticket_summary_for_hitl(display_name: str, reason: str) -> str:
    """
    Resumen breve para tickets en panel interno (chat/intake), no para el portal.

    No pregunta al usuario «¿deseas…?»; describe el hallazgo.
    """
    doc = str(display_name or "documento de la convocatoria").strip()
    motivo = humanize_clarification_reason(reason)
    return (
        f"Documento «{doc}»: {motivo}. "
        "Puede elevarse a la junta de aclaraciones desde el panel de preguntas."
    )


def build_junta_question_from_clarification_ticket(ticket: Dict[str, Any]) -> str:
    """
    Redacta una pregunta lista para la junta a partir de un ticket de aclaración.

    Ignora borradores internos legacy y usa ``display_name`` + ``reason``.
    """
    display = str(ticket.get("display_name") or "documento de la convocatoria").strip()
    reason_code = str(ticket.get("reason") or ticket.get("clarification_reason") or "").strip()
    raw_q = str(ticket.get("question") or "").strip()

    if raw_q and not is_internal_ticket_draft(raw_q) and is_junta_canonical_question(raw_q):
        return raw_q if raw_q.endswith("?") else f"{raw_q}?"

    motivo = humanize_clarification_reason(reason_code or "clarification_required")
    doc_ref = f"«{display}»"

    archivo = ticket.get("source_filename") or ticket.get("archivo_fuente")
    pagina = ticket.get("page") or ticket.get("pagina")
    ubic_extra = ""
    if archivo:
        ubic_extra = f" (según el expediente: {archivo}"
        if pagina:
            ubic_extra += f", p. {pagina}"
        ubic_extra += ")"

    if reason_code == "embedded_in_bases_pdf":
        return (
            f"Con respecto al formato {doc_ref} integrado en las bases de la convocatoria{ubic_extra}, "
            "¿debe el licitante reproducir exactamente la plantilla del PDF de bases, "
            "o existirá versión editable publicada por separado?"
        )

    return (
        f"Con respecto al documento o formato {doc_ref} previsto en las bases{ubic_extra}, "
        f"se observa que {motivo}. "
        "¿Podrá la convocante confirmar la publicación del formato oficial, "
        "el plazo para obtenerlo y si debe integrarse en la proposición?"
    )


def build_junta_question_grouped_missing_templates(
    display_names: List[str],
    *,
    reason: str = "required_annex_not_published",
) -> str:
    """
    Una sola pregunta cuando varios formatos oficiales no están como archivos sueltos.
    """
    names = [str(n or "").strip() for n in display_names if str(n or "").strip()]
    if not names:
        names = ["documentos de la convocatoria"]
    if len(names) <= 4:
        listing = ", ".join(f"«{n}»" for n in names)
    else:
        listing = ", ".join(f"«{n}»" for n in names[:3])
        listing += f" y {len(names) - 3} formatos adicionales citados en bases"
    motivo = humanize_clarification_reason(reason)
    return (
        f"Con respecto a los formatos {listing}, previstos en las bases, se observa que {motivo}. "
        "¿Podrá la convocante confirmar si deben tomarse del PDF de bases, "
        "publicar versiones editables por separado, y el plazo para integrarlos en la proposición?"
    )
