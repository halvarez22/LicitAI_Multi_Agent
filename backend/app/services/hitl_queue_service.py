"""
Cola HITL universal: deduplicación semántica, prioridad económica y exclusión de físicos en chat.

Ítem C — agenda post-Checkpoint 1.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Set

from app.services.document_deliverable_filter import normalize_deliverable_key

_ECONOMIC_TYPES = frozenset({"economic_price", "economic_validation_blocking"})
_HIGH_PRIORITY_TYPES = _ECONOMIC_TYPES | frozenset(
    {"profile_field_blocking", "quality_validation_blocking", "evidence_profile_conflict"}
)
_INTAKE_B_PREFIX = "INTAKE-COMP-"

_FISCAL_PHYSICAL_RE = re.compile(
    r"(?i)\b("
    r"declaraci[oó]n\s+anual|declaraci[oó]n\s+fiscal|declaraci[oó]n\s+de\s+integridad|"
    r"opini[oó]n\s+del\s+cumplimiento|opini[oó]n\s+positiva\s+del\s+sat|"
    r"opini[oó]n\s+(de\s+)?cumplimiento\s+(sat|estatal|federal|fiscal)|"
    r"constancia\s+de\s+situaci[oó]n\s+fiscal|c\s*\.\s*s\s*\.\s*f\.?|"
    r"sat\b|hacienda|infonavit|imss|"
    r"identificaci[oó]n\s+oficial|credencial\s+para\s+votar|"
    r"acta\s+constitutiva|poder\s+notarial|"
    r"comprobante\s+de\s+domicilio|"
    r"mipyme|micro\s*,?\s*peque[nñ]a|nacionalidad\s+mexicana|"
    r"no\s+colusi[oó]n|integridad\s+y\s+no\s+colusi"
    r")\b"
)

_PARTICIPATION_CHECK_PREFIX = "participacion.check_"

_STOPWORDS = frozenset(
    {"de", "la", "el", "los", "las", "en", "y", "o", "a", "del", "por", "con", "al", "su", "sus", "que", "para"}
)


def _norm_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def is_fiscal_or_physical_intake(label: str, question: str = "", field_target: str = "") -> bool:
    """True si la pregunta de intake refiere documento físico (SAT, INE, acta), no dato generable."""
    blob = " ".join((label, question, field_target)).strip()
    return bool(blob and _FISCAL_PHYSICAL_RE.search(blob))


def is_participation_procedural_intake(question: Dict[str, Any]) -> bool:
    """Requisitos literales del pliego (checklist participación) — no captura HITL en chat."""
    if not isinstance(question, dict):
        return False
    qid = str(question.get("question_id") or "")
    ft = str(question.get("field_target") or question.get("field") or "")
    label = str(question.get("label") or "")
    if qid.startswith("INTAKE-CHECK-"):
        return True
    if ft.startswith(_PARTICIPATION_CHECK_PREFIX):
        return True
    if label.startswith("Requisito:") and ft.startswith("participacion."):
        return True
    return False


def is_contractual_or_strategic_meta_intake(question: Dict[str, Any]) -> bool:
    """
    Condiciones de contrato, brechas Go/No-Go y gaps: panel de análisis, no chat.
    """
    from app.contracts.chat_queue_contract import is_panel_only_intake_item

    if not isinstance(question, dict):
        return False
    if is_panel_only_intake_item(question):
        return True
    prov = question.get("provenance_ui") if isinstance(question.get("provenance_ui"), dict) else {}
    if str(prov.get("reason") or "") in (
        "condicion_contractual",
        "brecha_detectada",
        "gap_analysis",
    ):
        return True
    qtext = _norm_text(question.get("question") or "")
    if "aceptas esta condicion" in qtext or "manifiesto correspondiente" in qtext:
        return True
    if "condicion critica sobre" in qtext and "estas de acuerdo" in qtext:
        return True
    return False


def is_deliverable_inventory_intake(question: Dict[str, Any]) -> bool:
    """
    True si la pregunta pide confirmar un anexo/formato del pliego (inventario UI),
    no un dato puntual de perfil o precio.
    """
    if not isinstance(question, dict):
        return False
    qid = str(question.get("question_id") or "")
    if qid.startswith("INTAKE-COMP-FOR-"):
        return True
    prov = question.get("provenance_ui") if isinstance(question.get("provenance_ui"), dict) else {}
    if str(prov.get("reason") or "") == "master_list_formatos":
        return True
    qtext = _norm_text(question.get("question") or "")
    if "para armar el expediente de" in qtext and "documento de referencia" in qtext:
        return True
    return False


def should_exclude_from_chat_queue(question: Dict[str, Any]) -> bool:
    """
    Excluye de ``pending_questions`` conversacional lo que debe vivir en checklist físico
    o en Documentos detectados (no solicitar anexos/formatos por chat).
    """
    if not isinstance(question, dict):
        return True
    if is_deliverable_inventory_intake(question):
        return True
    if is_contractual_or_strategic_meta_intake(question):
        return True
    if is_participation_procedural_intake(question):
        return True
    qid = str(question.get("question_id") or "")
    if qid.startswith(_INTAKE_B_PREFIX) and is_fiscal_or_physical_intake(
        str(question.get("label") or ""),
        str(question.get("question") or ""),
        str(question.get("field_target") or ""),
    ):
        return True
    label = str(question.get("label") or "")
    question_text = str(question.get("question") or "")
    ft = str(question.get("field_target") or question.get("field") or "")
    if is_fiscal_or_physical_intake(label, question_text, ft):
        if qid.startswith(_INTAKE_B_PREFIX) or qid.startswith("INTAKE-COMP-"):
            return True
        if str(question.get("type") or "") == "intake_planner":
            return True
    tipo = str(question.get("type") or "").lower()
    if tipo == "intake_physical_only":
        return True
    return False


def semantic_question_fingerprint(question: Dict[str, Any]) -> str:
    """
    Huella estable para deduplicar la misma pregunta con distinto ``field_target``.
    """
    qtype = str(question.get("type") or "unknown").lower()
    if qtype in _ECONOMIC_TYPES:
        field = str(question.get("field") or "").strip()
        if field:
            return f"eco|{field}"
        label = _norm_text(question.get("label") or question.get("question") or "")
        return f"eco|{label[:120]}"

    label = str(question.get("label") or question.get("question") or "").strip()
    cat = ""
    ft = str(question.get("field_target") or "")
    if "compliance." in ft:
        parts = ft.split(".")
        if len(parts) >= 2:
            cat = parts[1]
    key = normalize_deliverable_key(label, cat)
    qid = str(question.get("question_id") or "")
    if qid.startswith(_INTAKE_B_PREFIX):
        return f"intake|{key}"
    return f"{qtype}|{key}|{ft[:48]}"


def _question_sort_key(question: Dict[str, Any]) -> tuple:
    qtype = str(question.get("type") or "").lower()
    if qtype in _ECONOMIC_TYPES:
        tier = 0
    elif qtype in _HIGH_PRIORITY_TYPES:
        tier = 1
    elif str(question.get("question_id") or "").startswith(_INTAKE_B_PREFIX):
        tier = 3
    else:
        tier = 2
    blocking = 0 if question.get("blocking") else 1
    label = _norm_text(question.get("label") or question.get("question") or "")
    return (tier, blocking, label)


def dedupe_pending_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Elimina duplicados semánticos conservando la primera ocurrencia (más reciente en merge previo)."""
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        if should_exclude_from_chat_queue(q):
            continue
        fp = semantic_question_fingerprint(q)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(q)
    return out


def sort_pending_questions_priority(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordena: económico → bloqueos perfil → resto → intake tipo B al final (estable dentro de cada tier)."""
    indexed = list(enumerate(questions or []))

    def _key(entry: tuple[int, Dict[str, Any]]) -> tuple:
        _pos, question = entry
        qtype = str(question.get("type") or "").lower()
        if qtype in _ECONOMIC_TYPES:
            tier = 0
        elif qtype in _HIGH_PRIORITY_TYPES:
            tier = 1
        elif str(question.get("question_id") or "").startswith(_INTAKE_B_PREFIX):
            tier = 3
        else:
            tier = 2
        blocking = 0 if question.get("blocking") else 1
        return (tier, blocking, _pos)

    return [q for _, q in sorted(indexed, key=_key)]


def sanitize_chat_pending_questions(
    pending: Iterable[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Cola conversacional: solo perfil puntual y precios (sin meta-análisis ni inventario)."""
    from app.services.document_quality_ux import normalize_expediente_pending_questions
    from app.services.chat_fill_quality_queue_policy import should_exclude_fill_quality_from_chat
    from app.services.mini_dictamen_anexos_service import strip_chat_excluded_pending_questions
    from app.services.obra_chat_queue_policy import sanitize_obra_chat_pending_questions

    normalized = normalize_expediente_pending_questions(list(pending or []), session_state)
    out: List[Dict[str, Any]] = []
    for q in strip_chat_excluded_pending_questions(normalized):
        if should_exclude_from_chat_queue(q):
            continue
        if should_exclude_fill_quality_from_chat(q, session_state):
            continue
        out.append(q)
    out = sanitize_obra_chat_pending_questions(out, session_state)
    return normalize_pending_queue(out)


def normalize_pending_queue(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pipeline estándar: filtrar físicos, deduplicar, priorizar."""
    return sort_pending_questions_priority(dedupe_pending_questions(list(questions or [])))


def merge_pending_queues(
    *queues: List[Dict[str, Any]],
    prepend_economic: bool = True,
) -> List[Dict[str, Any]]:
    """
    Fusiona varias listas sin duplicar; por defecto deja económico al frente tras normalizar.
    """
    merged: List[Dict[str, Any]] = []
    for qlist in queues:
        for q in qlist or []:
            if isinstance(q, dict):
                merged.append(q)
    if prepend_economic:
        economic = [q for q in merged if str(q.get("type") or "") in _ECONOMIC_TYPES]
        rest = [q for q in merged if str(q.get("type") or "") not in _ECONOMIC_TYPES]
        merged = economic + rest
    return normalize_pending_queue(merged)


def intake_question_copy(nombre: str) -> str:
    """Copy de expediente (no contabilidad) para requisitos con datos del licitante."""
    return (
        f"Para armar el expediente de **{nombre}**, ¿ya tienes el dato o documento de referencia "
        f"que debemos reflejar en la propuesta? Responde con el valor o indica si lo aportarás aparte."
    )
