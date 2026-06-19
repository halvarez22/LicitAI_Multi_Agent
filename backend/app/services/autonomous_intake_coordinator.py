"""
Coordinador delgado de intake autónomo (Fase 1 / Semana 1).

Consolida estado post-análisis sin duplicar ``pending_questions`` ni bloquear el orquestador.
Delega deduplicación a ``hitl_queue_service`` y clasificación a ``triage_context``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging_config import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _question_key(q: Dict[str, Any]) -> str:
    if not isinstance(q, dict):
        return ""
    return str(q.get("question_id") or q.get("field") or q.get("field_target") or "")


def _triage_snapshot(triage_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    triage = triage_context if isinstance(triage_context, dict) else {}
    return {
        "tender_category": str(triage.get("tender_category") or ""),
        "law": str(triage.get("law") or ""),
        "procedure_type": str(triage.get("procedure_type") or ""),
    }


def build_autonomous_intake_state(
    *,
    session_state: Dict[str, Any],
    mode: str,
    merged_pending: List[Dict[str, Any]],
    dedupe_removed: int,
    sources_merged: List[str],
) -> Dict[str, Any]:
    """
    Construye el bloque ``autonomous_intake`` versionado para persistir en sesión.

    Args:
        session_state: Estado fresco de la sesión.
        mode: Modo del orquestador (``full``, ``analysis_only``, etc.).
        merged_pending: Cola ya normalizada/deduplicada.
        dedupe_removed: Cuántos ítems se descartaron por huella duplicada.
        sources_merged: Fuentes consolidadas (p. ej. intake_plan, pending_questions).

    Returns:
        Dict listo para ``state_data.autonomous_intake``.
    """
    triage = _triage_snapshot(session_state.get("triage_context"))
    blocking = sum(1 for q in merged_pending if q.get("blocking"))
    prev = session_state.get("autonomous_intake") if isinstance(session_state.get("autonomous_intake"), dict) else {}
    status = "complete" if not merged_pending else "collecting_gaps"
    if merged_pending and blocking == 0:
        status = "queue_ready"

    return {
        "version": SCHEMA_VERSION,
        "enabled": True,
        "status": status,
        "last_run_at": _now_iso(),
        "last_run_mode": mode,
        "triage": triage,
        "queue_stats": {
            "total_pending": len(merged_pending),
            "blocking_count": blocking,
            "dedupe_removed": dedupe_removed,
        },
        "sources_merged": list(sources_merged),
        "first_run_at": str(prev.get("first_run_at") or _now_iso()),
    }


def consolidate_pending_from_intake_plan(
    session_state: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    """
    Fusiona preguntas del ``intake_plan`` con la cola existente sin duplicar.

    Returns:
        Tupla (cola_merged, dedupe_removed, sources_merged).
    """
    from app.services.hitl_queue_service import (
        merge_pending_queues,
        normalize_pending_queue,
        semantic_question_fingerprint,
        should_exclude_from_chat_queue,
    )

    plan_raw = session_state.get("intake_plan")
    plan = plan_raw if isinstance(plan_raw, dict) else {}
    planner_questions = [q for q in list(plan.get("questions") or []) if isinstance(q, dict)]

    existing_pending = [q for q in list(session_state.get("pending_questions") or []) if isinstance(q, dict)]
    corp_checklist = [c for c in list(plan.get("checklist_corporativo") or []) if isinstance(c, dict)]
    corp_keys = {_question_key(c) for c in corp_checklist if _question_key(c)}

    existing_pending = [q for q in existing_pending if _question_key(q) not in corp_keys]
    existing_pending = [q for q in existing_pending if not should_exclude_from_chat_queue(q)]

    existing_keys = {_question_key(q) for q in existing_pending if _question_key(q)}
    new_to_add = [
        q
        for q in planner_questions
        if _question_key(q) not in existing_keys and not should_exclude_from_chat_queue(q)
    ]

    raw_merged = merge_pending_queues(existing_pending, new_to_add)
    normalized = normalize_pending_queue(raw_merged)

    seen: set[str] = set()
    dedupe_removed = 0
    for q in raw_merged:
        if should_exclude_from_chat_queue(q):
            continue
        fp = semantic_question_fingerprint(q)
        if fp in seen:
            dedupe_removed += 1
        else:
            seen.add(fp)

    sources: List[str] = []
    if existing_pending:
        sources.append("pending_questions")
    if planner_questions:
        sources.append("intake_plan")

    return normalized, dedupe_removed, sources


async def run_post_analysis_checkpoint(
    memory: Any,
    session_id: str,
    *,
    mode: str,
) -> Optional[Dict[str, Any]]:
    """
    Hook post-análisis: consolida cola HITL y persiste ``autonomous_intake``.

    No lanza excepciones al orquestador; devuelve snapshot o None si está deshabilitado.

    Args:
        memory: Adaptador de memoria de sesión.
        session_id: ID de sesión.
        mode: Modo de corrida del orquestador.

    Returns:
        Bloque ``autonomous_intake`` persistido, o None si la bandera está apagada.
    """
    from app.config.settings import settings

    if not settings.AUTONOMOUS_INTAKE_ENABLED:
        return None
    if mode not in ("full", "analysis_only"):
        return None

    try:
        fresh = await memory.get_session(session_id) or {}
        merged, dedupe_removed, sources = consolidate_pending_from_intake_plan(fresh)
        intake_block = build_autonomous_intake_state(
            session_state=fresh,
            mode=mode,
            merged_pending=merged,
            dedupe_removed=dedupe_removed,
            sources_merged=sources,
        )

        updates: Dict[str, Any] = {"autonomous_intake": intake_block}
        if merged != list(fresh.get("pending_questions") or []):
            updates["pending_questions"] = merged

        await memory.save_session(session_id, updates)

        logger.info(
            "autonomous_intake_post_analysis",
            session_id=session_id,
            mode=mode,
            pending=len(merged),
            dedupe_removed=dedupe_removed,
            status=intake_block.get("status"),
        )
        return intake_block
    except Exception as exc:
        logger.warning(
            "autonomous_intake_post_analysis_failed",
            session_id=session_id,
            error=str(exc)[:200],
        )
        return None
