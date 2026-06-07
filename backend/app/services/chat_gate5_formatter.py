"""
Formateo Gate 5 SUPER ISSUE: ≤3 líneas visibles + un solo CTA humano.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.chat_stop_reason_map import (
    humanize_stop_reason,
    sanitize_user_visible_text,
    single_cta_for_context,
)


def format_gate5_message(
    *,
    status: str,
    cta: str,
    detail: str = "",
) -> str:
    """
    Compone respuesta de chat acotada: máximo 3 líneas (2 de estado + 1 CTA).
    """
    status_line = sanitize_user_visible_text(str(status or "").strip())
    detail_line = sanitize_user_visible_text(str(detail or "").strip())
    cta_line = sanitize_user_visible_text(str(cta or "").strip())

    lines: List[str] = []
    if status_line:
        lines.append(status_line)
    if detail_line and len(lines) < 2:
        lines.append(detail_line)
    lines = lines[:2]
    if cta_line:
        lines.append(f"**Siguiente paso:** {cta_line}")
    return "\n".join(lines[:3]).strip()


def build_compact_session_resume(state: Dict[str, Any]) -> str:
    """
    Mensaje de reanudación determinista (Gate 5) desde estado de sesión.
    """
    session_name = str(state.get("name") or "esta licitación")
    decision = state.get("last_orchestrator_decision") if isinstance(state.get("last_orchestrator_decision"), dict) else {}
    stop_reason = str(decision.get("stop_reason") or "IDLE")

    pending = list(state.get("pending_questions") or [])
    eco_pending = [
        q
        for q in pending
        if str(q.get("type") or "")
        in ("economic_price", "economic_price_matrix", "economic_validation_blocking")
    ]

    status = humanize_stop_reason(stop_reason)
    detail = f"Retomamos **{session_name}**."
    if eco_pending:
        cur = eco_pending[0]
        label = str(cur.get("label") or "Precio pendiente")
        detail = f"Captura pendiente: **{label}** ({len(eco_pending)} en cola)."

    cta = single_cta_for_context(
        stop_reason=stop_reason,
        has_economic_pending=bool(eco_pending),
    )
    return format_gate5_message(status=status, detail=detail, cta=cta)


def build_compact_meta_status(
    *,
    stop_reason: Optional[str],
    pending_questions: Optional[List[Dict[str, Any]]] = None,
    current_idx: int = 0,
) -> str:
    """Estado META compacto para «cómo vamos» / VER_ESTADO."""
    pending = list(pending_questions or [])
    eco_pending = [
        q
        for q in pending
        if str(q.get("type") or "")
        in ("economic_price", "economic_price_matrix", "economic_validation_blocking")
    ]
    explanation = humanize_stop_reason(stop_reason)
    detail = ""
    if pending:
        idx = max(0, min(int(current_idx or 0), len(pending) - 1))
        label = str(pending[idx].get("label") or "Dato pendiente")
        detail = f"Pendiente actual ({idx + 1}/{len(pending)}): **{label}**."

    cta = single_cta_for_context(
        stop_reason=stop_reason,
        has_economic_pending=bool(eco_pending),
    )
    return format_gate5_message(status=explanation, detail=detail, cta=cta)


def count_visible_lines(text: str) -> int:
    """Cuenta líneas no vacías (para tests Gate 5)."""
    return len([ln for ln in str(text or "").splitlines() if ln.strip()])
