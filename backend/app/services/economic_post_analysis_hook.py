"""
Hook HRU post-análisis: prepara captura económica proactiva en sesión.

Se ejecuta tras ``stage_completed:analysis`` — universal, sin mapas por licitación.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.services.economic_canonical_v1 import sync_economic_canonical_v1
from app.services.structured_economic_price_mapper import build_structured_price_slots
from app.services.structured_price_capture import prepare_structured_price_capture


def _merge_pending_questions(
    existing: List[Dict[str, Any]],
    new_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Conserva pendientes no económicos y añade cola económica."""
    keep = [
        q
        for q in (existing or [])
        if isinstance(q, dict)
        and str(q.get("type") or "")
        not in ("economic_price", "economic_price_matrix", "economic_validation_blocking")
    ]
    return keep + list(new_items or [])


async def run_economic_post_analysis_hook(
    memory: Any,
    session_id: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Tras análisis exitoso, encola captura económica si hay slots sin precio.

    Returns:
        Resumen del hook o ``None`` si no aplicó.
    """
    if not bool(getattr(settings, "ECONOMIC_POST_ANALYSIS_HOOK_ENABLED", True)):
        return None

    state = dict(session_state or {})
    if memory is not None:
        try:
            fresh = await memory.get_session(session_id)
            if isinstance(fresh, dict):
                state = fresh
        except Exception:
            pass

    rows = list(state.get("session_line_items") or [])
    if not rows:
        return None

    inputs = state.get("economic_user_inputs") or {}
    slots = build_structured_price_slots(rows, inputs if isinstance(inputs, dict) else {})
    missing = [s for s in slots if s.get("captured_price") is None]
    if not missing:
        updates = sync_economic_canonical_v1(state)
        if updates.get("economic_canonical_v1"):
            await memory.save_session(session_id, updates)
        return {"status": "already_complete", "missing_count": 0}

    pending, intro, capture_updates = prepare_structured_price_capture(
        state,
        missing,
        session_id=session_id,
    )
    merged_state = {**state, **capture_updates}
    canonical_updates = sync_economic_canonical_v1(merged_state)
    updates = {
        **capture_updates,
        **canonical_updates,
        "pending_questions": _merge_pending_questions(
            list(state.get("pending_questions") or []),
            pending,
        ),
        "current_question_index": 0,
        "last_economic_waiting_hints": {
            "missing_count": len(missing),
            "intro": intro[:500],
            "source": "post_analysis_hook",
        },
    }
    await memory.save_session(session_id, updates)
    return {
        "status": "queued",
        "missing_count": len(missing),
        "capture_mode": updates.get("economic_capture_mode"),
        "pending_questions_added": len(pending),
    }
