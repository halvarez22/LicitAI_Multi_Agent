"""
Hook HRU post-análisis: prepara captura técnica proactiva en sesión (F9.5).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.config.settings import settings
from app.services.technical_canonical_v1 import sync_technical_canonical_v1
from app.services.technical_slot_mapper import (
    build_technical_slot_inventory,
    load_technical_capture_policy,
    technical_capture_status,
)


def _capture_mode_for_count(slot_count: int) -> str:
    pol = load_technical_capture_policy()
    threshold = int(pol.get("matrix_capture_min_slots") or 5)
    return "matrix" if slot_count >= threshold else "one_by_one"


async def run_technical_post_analysis_hook(
    memory: Any,
    session_id: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not bool(getattr(settings, "TECHNICAL_POST_ANALYSIS_HOOK_ENABLED", True)):
        return None

    state = dict(session_state or {})
    if memory is not None:
        try:
            fresh = await memory.get_session(session_id)
            if isinstance(fresh, dict):
                state = fresh
        except Exception:
            pass

    slots = build_technical_slot_inventory(state)
    if not slots:
        return None

    cap = technical_capture_status(state)
    if cap.get("capture_complete"):
        updates = sync_technical_canonical_v1(state)
        if updates.get("technical_canonical_v1"):
            await memory.save_session(session_id, updates)
        return {"status": "already_complete", "missing_count": 0}

    missing = [s for s in slots if str(s.get("capture_mode") or "") != "upload_only"]
    mode = _capture_mode_for_count(len(slots))
    updates = {
        **sync_technical_canonical_v1(state),
        "technical_capture_mode": mode,
        "last_technical_waiting_hints": {
            "missing_count": int(cap.get("missing") or 0),
            "source": "post_analysis_hook",
        },
        "technical_post_analysis_hook_pending": True,
    }
    await memory.save_session(session_id, updates)
    return {
        "status": "queued",
        "missing_count": len(missing),
        "capture_mode": mode,
        "slot_count": len(slots),
    }
