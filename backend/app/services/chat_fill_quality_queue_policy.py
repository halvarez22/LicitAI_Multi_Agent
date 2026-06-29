"""
Política universal HRU: bloqueos del gate de llenado documental en chat vs panel.

Aplica a obra, servicios, suministros, etc. — sin mapas por licitación.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def fill_quality_issues_from_session(
    session_state: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(session_state, dict):
        return []
    hint = session_state.get("last_document_fill_quality_waiting_hints")
    if not isinstance(hint, dict):
        return []
    raw = hint.get("issues")
    if not isinstance(raw, list):
        return []
    return [i for i in raw if isinstance(i, dict)]


def is_fill_quality_chat_question(question: Dict[str, Any]) -> bool:
    if not isinstance(question, dict):
        return False
    qtype = str(question.get("type") or "").lower()
    field_key = str(
        question.get("field") or question.get("field_target") or ""
    ).strip().lower()
    if qtype == "quality_validation_blocking" and field_key in {
        "quality.fill.review",
        "document_fill_quality_gate",
    }:
        return True
    if field_key in {"quality.fill.review", "document_fill_quality_gate"}:
        return True
    return qtype in {"document_fill_quality_gate_blocking", "document_fill_quality_gate"}


def fill_quality_needs_chat_capture(
    issues: List[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    True si el usuario debe aportar RFC, precios o clientes en chat.
    False si basta **Generar** en panel (plantillas / [Consignar]).
    """
    if not issues:
        return False
    from app.services.obra_chat_queue_policy import filter_obra_fill_quality_issues
    from app.services.document_fill_ux_messages import classify_fill_issues

    filtered = filter_obra_fill_quality_issues(list(issues), session_state)
    if not filtered:
        return False
    needs_profile, needs_clients, needs_economic, _needs_shell = classify_fill_issues(filtered)
    return bool(needs_profile or needs_clients or needs_economic)


def should_exclude_fill_quality_from_chat(
    question: Dict[str, Any],
    session_state: Optional[Dict[str, Any]],
) -> bool:
    """No promover al chat pausas por plantilla; resolver en panel."""
    if not is_fill_quality_chat_question(question):
        return False
    issues = fill_quality_issues_from_session(session_state)
    if not issues:
        return True
    return not fill_quality_needs_chat_capture(issues, session_state)


def should_skip_fill_quality_rag_reminder(
    question: Dict[str, Any],
    session_state: Optional[Dict[str, Any]],
) -> bool:
    """No pegar «Datos para llenar documentos» tras respuestas RAG sobre bases."""
    if not is_fill_quality_chat_question(question):
        return False
    label = str(question.get("label") or "").strip().lower()
    if label == "datos para llenar documentos":
        return should_exclude_fill_quality_from_chat(question, session_state)
    return should_exclude_fill_quality_from_chat(question, session_state)
