"""
UX HRU para gates de calidad documental y etiquetas de progreso del expediente.

Fuente canónica: ``app/contracts/document_quality_ux_messages.json``.
Traduce ``error_type`` / ``reason`` forense a copy accionable (Gate 5).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.chat_gate5_formatter import format_gate5_message

_UX_PATH = Path(__file__).resolve().parents[1] / "contracts" / "document_quality_ux_messages.json"

_QUALITY_PENDING_TYPES = frozenset(
    {"document_quality_gate_blocking", "quality_validation_blocking"}
)
_TECHNICAL_JARGON_RE = re.compile(
    r"(?i)\b("
    r"presentar_fisico|informativo|tipo_accion|evidence_match|unknown_ratio|"
    r"anclas?\s+de\s+evidencia|reclasificar|calidad\s+estructural|integridad"
    r")\b"
)


@lru_cache(maxsize=1)
def load_document_quality_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_document_quality_ux_messages().get("messages_version") or "")


def _session_name(session_state: Optional[Dict[str, Any]]) -> str:
    state = session_state or {}
    name = str(state.get("name") or "").strip()
    return name or "esta licitación"


def _reason_template(reason: str) -> Dict[str, str]:
    gate = (load_document_quality_ux_messages().get("document_quality_gate") or {})
    reasons = gate.get("reasons") if isinstance(gate.get("reasons"), dict) else {}
    key = str(reason or "").strip() or "default"
    tpl = reasons.get(key) if isinstance(reasons.get(key), dict) else None
    if not tpl:
        tpl = reasons.get("default") if isinstance(reasons.get("default"), dict) else {}
    return {str(k): str(v) for k, v in (tpl or {}).items()}


def _format_ctx(session_state: Optional[Dict[str, Any]], metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    m = metrics if isinstance(metrics, dict) else {}
    total = int(m.get("total_items") or 0)
    unknown = int(m.get("unknown_count") or 0)
    if unknown <= 0 and total > 0:
        unknown_ratio = float(m.get("unknown_ratio") or 0.0)
        unknown = max(1, int(round(unknown_ratio * total)))
    return {
        "session_name": _session_name(session_state),
        "ambiguous_count": max(unknown, 1),
    }


def build_document_quality_gate_message(
    *,
    gate: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
    stage: str = "technical",
) -> str:
    """Mensaje Gate 5 para chat cuando el gate documental bloquea."""
    reason = str(gate.get("reason") or "")
    metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
    tpl = _reason_template(reason)
    ctx = _format_ctx(session_state, metrics)
    status = tpl.get("status", "").format(**ctx)
    detail = tpl.get("detail", "").format(**ctx)
    cta = tpl.get("cta", "").format(**ctx)
    return format_gate5_message(status=status, detail=detail, cta=cta)


def build_document_quality_agent_pause_message(*, stage: str = "technical") -> str:
    gate = load_document_quality_ux_messages().get("document_quality_gate") or {}
    key = "agent_pause_formats" if str(stage or "").lower() in ("formats", "admin") else "agent_pause_technical"
    return str(gate.get(key) or gate.get("agent_pause_technical") or "")


def build_document_quality_pending_question(
    *,
    gate: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
    stage: str = "technical",
) -> Dict[str, Any]:
    """
    Ítem HITL para ``pending_questions`` — copy de negocio, trazabilidad en provenance_ui.
    """
    reason = str(gate.get("reason") or "")
    metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
    gate_cfg = load_document_quality_ux_messages().get("document_quality_gate") or {}
    label = str(gate_cfg.get("pending_label") or "Confirmar documentos del pliego")
    question = build_document_quality_gate_message(
        gate=gate, session_state=session_state, stage=stage
    )
    return {
        "field": "quality.classification.review",
        "label": label,
        "question": question,
        "type": "quality_validation_blocking",
        "is_blocking": True,
        "priority": "BLOQUEANTE",
        "question_id": f"DQ-{stage[:3].upper()}-001",
        "required_evidence": "confirmacion_plan_documentos",
        "provenance_ui": {
            "source": "document_quality_gate",
            "confidence": 0.9,
            "reason": reason,
            "stage": stage,
            "metrics": metrics,
        },
        "document_hint": f"gate_reason={reason}",
    }


def build_quality_hint_pending_question(
    *,
    hint: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Promueve ``last_document_quality_waiting_hints`` a pregunta HITL humanizada."""
    gate = {
        "reason": str(hint.get("reason") or "default"),
        "metrics": hint.get("metrics") if isinstance(hint.get("metrics"), dict) else {},
    }
    return build_document_quality_pending_question(
        gate=gate,
        session_state=session_state,
        stage="technical",
    )


def humanize_document_quality_question_text(
    question: str,
    *,
    session_state: Optional[Dict[str, Any]] = None,
    gate_reason: str = "",
) -> str:
    """Reemplaza copy forense legacy si se detecta jerga técnica."""
    raw = str(question or "").strip()
    if not raw or not _TECHNICAL_JARGON_RE.search(raw):
        return raw
    gate = {
        "reason": gate_reason or "default",
        "metrics": {},
    }
    hints = (session_state or {}).get("last_document_quality_waiting_hints")
    if isinstance(hints, dict):
        gate["reason"] = str(hints.get("reason") or gate["reason"])
        if isinstance(hints.get("metrics"), dict):
            gate["metrics"] = hints["metrics"]
    return build_document_quality_gate_message(
        gate=gate, session_state=session_state, stage="technical"
    )


def normalize_document_quality_pending_item(
    question: Dict[str, Any],
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convierte ``document_quality_gate_blocking`` legacy a ``quality_validation_blocking`` HRU."""
    if not isinstance(question, dict):
        return question
    qtype = str(question.get("type") or "")
    field = str(question.get("field") or "")
    if qtype != "document_quality_gate_blocking" and field != "document_quality_gate":
        qtext = str(question.get("question") or "")
        if qtype == "quality_validation_blocking" and _TECHNICAL_JARGON_RE.search(qtext):
            updated = dict(question)
            prov = updated.get("provenance_ui") if isinstance(updated.get("provenance_ui"), dict) else {}
            updated["question"] = humanize_document_quality_question_text(
                qtext,
                session_state=session_state,
                gate_reason=str(prov.get("reason") or ""),
            )
            return updated
        return question

    hint = (session_state or {}).get("last_document_quality_waiting_hints")
    if isinstance(hint, dict) and hint.get("reason"):
        return build_quality_hint_pending_question(hint=hint, session_state=session_state)

    reason = ""
    hint_match = re.search(r"Motivo gate:\s*([^.]+)", str(question.get("document_hint") or ""))
    if hint_match:
        reason = hint_match.group(1).strip()
    gate = {"reason": reason or "default", "metrics": {}}
    return build_document_quality_pending_question(
        gate=gate, session_state=session_state,
        stage="formats" if "administrativ" in str(question.get("label") or "").lower() else "technical",
    )


def normalize_expediente_pending_questions(
    pending: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Pipeline HRU sobre cola conversacional: humaniza gates documentales."""
    out: List[Dict[str, Any]] = []
    for q in pending or []:
        if isinstance(q, dict):
            out.append(normalize_document_quality_pending_item(q, session_state))
    return out


def build_expediente_progress_label(
    current: int,
    total: int,
) -> str:
    prog = load_document_quality_ux_messages().get("expediente_progress") or {}
    tpl = str(prog.get("progress_step") or "Paso {current} de {total}")
    return tpl.format(current=max(1, current), total=max(1, total))


def ui_shell_message(key: str, default: str = "") -> str:
    shell = load_document_quality_ux_messages().get("ui_shell") or {}
    return str(shell.get(key) or default)


def expediente_progress_copy(key: str, default: str = "") -> str:
    prog = load_document_quality_ux_messages().get("expediente_progress") or {}
    return str(prog.get(key) or default)
