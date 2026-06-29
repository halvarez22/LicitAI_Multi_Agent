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

_STALE_GENERATION_STOP_REASONS = frozenset(
    {
        "INCOMPLETE_FORMATS_DATA",
        "INCOMPLETE_FORMAT_DATA",
        "DELIVERY_COVERAGE_GAP",
        "PACKAGING_VALIDATION_FAILED",
        "PACKAGING_INCOMPLETE_SOBRES",
        "MINI_DICTAMEN_BLOCKED",
    }
)


def _has_analysis_complete(state: Dict[str, Any]) -> bool:
    for task in state.get("tasks_completed") or []:
        if isinstance(task, dict) and str(task.get("task") or "") == "stage_completed:analysis":
            return True
    return False


def _has_economic_chat_pending(state: Dict[str, Any]) -> bool:
    pending = list(state.get("pending_questions") or [])
    return any(
        str(q.get("type") or "")
        in ("economic_price", "economic_price_matrix", "economic_validation_blocking")
        for q in pending
        if isinstance(q, dict)
    )


def _should_use_expediente_plan_bootstrap(state: Dict[str, Any], stop_reason: str) -> bool:
    """Bootstrap HRU universal tras análisis, sin cola económica activa."""
    if not _has_analysis_complete(state):
        return False
    if _has_economic_chat_pending(state):
        return False
    if stop_reason in _STALE_GENERATION_STOP_REASONS or stop_reason in (
        "IDLE",
        "ANALYSIS_COMPLETED",
    ):
        return True
    return True


def build_obra_documentary_bootstrap(state: Dict[str, Any]) -> str:
    """Retrocompat: delega al bootstrap universal de expediente."""
    from app.services.chat_expediente_bootstrap_service import build_expediente_plan_bootstrap

    return build_expediente_plan_bootstrap(state)


def format_gate5_message(
    *,
    status: str,
    cta: str,
    detail: str = "",
) -> str:
    """Compone respuesta de chat acotada: máximo 3 líneas (2 de estado + 1 CTA)."""
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
    """Mensaje de reanudación determinista (Gate 5) desde estado de sesión."""
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

    if _should_use_expediente_plan_bootstrap(state, stop_reason):
        from app.services.chat_expediente_bootstrap_service import build_expediente_plan_bootstrap

        return build_expediente_plan_bootstrap(state)

    status = humanize_stop_reason(stop_reason)
    if stop_reason in _STALE_GENERATION_STOP_REASONS and _has_analysis_complete(state):
        status = (
            "El análisis de bases está listo. "
            "Si una generación anterior quedó incompleta, revisa los anexos en el panel antes de volver a generar."
        )

    detail = f"Continuamos con **{session_name}**."
    if eco_pending:
        cur = eco_pending[0]
        label = str(cur.get("label") or "Precio pendiente")
        detail = f"Captura pendiente: **{label}** ({len(eco_pending)} en cola)."

    cta = single_cta_for_context(
        stop_reason=stop_reason,
        has_economic_pending=bool(eco_pending),
    )
    if (
        _has_analysis_complete(state)
        and not eco_pending
        and stop_reason in _STALE_GENERATION_STOP_REASONS
    ):
        cta = (
            "Revisa **Formatos/Anexos Detectados** y pulsa **Generar**; "
            "consigna en los Word los datos marcados **[Consignar]**."
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
