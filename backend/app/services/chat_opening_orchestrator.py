"""
Orquestador único de apertura del chat (F11).

Precedencia: saludo/apertura con empresa → briefing + primer paso (determinista).
Evita carreras entre mission bootstrap, proactive económico y proactive técnico.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.services.expediente_mission_router import is_greeting_or_opening, resolve_expediente_mission


@dataclass
class ChatOpeningResult:
    """Resultado determinista de apertura conversacional."""

    message: str
    mission_id: str
    opening_v1: Dict[str, Any] = field(default_factory=dict)
    briefing_v1: Dict[str, Any] = field(default_factory=dict)
    present_on_greeting: bool = True


def chat_opening_orchestrator_enabled() -> bool:
    return bool(getattr(settings, "CHAT_OPENING_ORCHESTRATOR_ENABLED", True))


def _has_analysis_complete(state: Dict[str, Any]) -> bool:
    for task in state.get("tasks_completed") or []:
        if isinstance(task, dict) and str(task.get("task") or "") == "stage_completed:analysis":
            return True
    return False


def _is_mid_conversation_blocking(
    pending: List[Dict[str, Any]],
    current_idx: int,
    user_query: str,
) -> bool:
    """True si el usuario responde una pregunta HITL activa (no es apertura)."""
    if not pending:
        return False
    if is_greeting_or_opening(user_query):
        return False
    if 0 <= current_idx < len(pending):
        q = pending[current_idx]
        if isinstance(q, dict) and str(q.get("type") or "") not in ("", "profile", "profile_field"):
            return True
    return False


def resolve_chat_opening(
    *,
    session_state: Dict[str, Any],
    pending_questions: List[Dict[str, Any]],
    current_idx: int,
    user_query: str,
    company_id: Optional[str] = None,
) -> Optional[ChatOpeningResult]:
    """
    Resuelve mensaje de apertura unificado.

    Returns:
        ``None`` si no aplica (orquestador off, sin empresa, mid-conversation, sin análisis).
    """
    if not chat_opening_orchestrator_enabled():
        return None
    if not company_id:
        return None
    if not is_greeting_or_opening(user_query):
        return None
    if _is_mid_conversation_blocking(pending_questions, current_idx, user_query):
        return None
    if not _has_analysis_complete(session_state):
        return None

    from app.services.convocatoria_briefing_service import (
        convocatoria_briefing_enabled,
        merge_convocatoria_briefing_v1,
    )
    from app.services.convocatoria_briefing_ux import render_opening_message

    state = dict(session_state)
    briefing = state.get("convocatoria_briefing_v1")
    if convocatoria_briefing_enabled():
        updates = merge_convocatoria_briefing_v1(state)
        if updates.get("convocatoria_briefing_v1"):
            briefing = updates["convocatoria_briefing_v1"]
            state.update(updates)
        elif not isinstance(briefing, dict):
            briefing = merge_convocatoria_briefing_v1(state).get("convocatoria_briefing_v1")
            if not isinstance(briefing, dict):
                from app.services.convocatoria_briefing_service import build_convocatoria_briefing_canonical_v1

                briefing = build_convocatoria_briefing_canonical_v1(state)

    mission = resolve_expediente_mission(state)
    if not isinstance(briefing, dict):
        if mission is None:
            return None
        return ChatOpeningResult(
            message=mission.message,
            mission_id=mission.mission_id,
            opening_v1={
                "mission_id": mission.mission_id,
                "provenance_ui": mission.provenance,
                "source": "expediente_mission_router_fallback",
            },
        )

    message = render_opening_message(session_state=state, briefing=briefing)
    track = str(briefing.get("recommended_first_track") or "economic")
    mission_id = {
        "economic": "economic_capture",
        "technical": "technical_capture",
        "administrative": "administrative_documents",
    }.get(track, "economic_capture")
    if mission is not None:
        mission_id = mission.mission_id

    return ChatOpeningResult(
        message=message,
        mission_id=mission_id,
        briefing_v1=briefing,
        opening_v1={
            "mission_id": mission_id,
            "recommended_first_track": track,
            "provenance_ui": {
                "source": "convocatoria_briefing_v1",
                "content_hash": briefing.get("content_hash"),
                "policy_version": briefing.get("policy_version"),
            },
        },
        present_on_greeting=True,
    )


def should_skip_proactive_opening_handlers(user_query: str) -> bool:
    """True cuando el orquestador F11 debe ser la única vía de apertura."""
    return chat_opening_orchestrator_enabled() and is_greeting_or_opening(user_query)
