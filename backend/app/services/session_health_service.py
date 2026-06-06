"""
Salud de artefactos de sesión (P2-04): conteos, stale y recomendación de rehidratación.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.reference_session_baseline import (
    compare_counts_to_baseline,
    extract_session_counts,
    load_baseline,
)


def _has_compliance(state: Dict[str, Any]) -> bool:
    cml = state.get("compliance_master_list")
    if not isinstance(cml, dict):
        return False
    return any(cml.get(z) for z in ("administrativo", "tecnico", "formatos"))


def assess_session_health(
    session_id: str,
    state: Dict[str, Any],
    *,
    use_baseline: bool = True,
) -> Dict[str, Any]:
    """
    Evalúa artefactos persistidos sin llamadas RAG pesadas.

    Returns:
        dict con ``artifacts``, ``stale``, ``rehydrate_recommended``, ``healthy``.
    """
    if not state:
        return {
            "session_id": session_id,
            "healthy": False,
            "rehydrate_recommended": False,
            "stale": ["session_not_found"],
            "artifacts": {},
        }

    counts = extract_session_counts(state)
    snap = state.get("bases_analysis_snapshot") or {}
    stale: List[str] = []

    if snap.get("pending_reanalysis"):
        stale.append("bases_pending_reanalysis")

    if state.get("rehydrate_last_error"):
        stale.append("rehydrate_last_error")

    if _has_compliance(state):
        if not counts.get("has_dictamen"):
            stale.append("dictamen_missing_with_compliance")
        if counts.get("hitos", 0) < 1:
            stale.append("hitos_missing_with_compliance")
        if counts.get("junta_items", 0) < 1:
            stale.append("junta_missing_with_compliance")
        if counts.get("sobre_1_tecnico", 0) < 1:
            stale.append("candidates_missing_with_compliance")
    elif counts.get("has_dictamen"):
        stale.append("dictamen_without_compliance")

    baseline_violations: List[str] = []
    if use_baseline:
        try:
            bl = load_baseline(session_id)
            baseline_violations = compare_counts_to_baseline(counts, bl)
            for v in baseline_violations:
                stale.append(f"baseline:{v}")
        except FileNotFoundError:
            pass

    rehydrate_recommended = bool(
        snap.get("pending_reanalysis")
        or state.get("rehydrate_last_error")
        or (
            _has_compliance(state)
            and (
                baseline_violations
                or not counts.get("has_dictamen")
                or counts.get("junta_items", 0) < 1
                or counts.get("hitos", 0) < 1
            )
        )
    )

    healthy = not stale and not rehydrate_recommended

    payload: Dict[str, Any] = {
        "session_id": session_id,
        "healthy": healthy,
        "rehydrate_recommended": rehydrate_recommended,
        "stale": sorted(set(stale)),
        "baseline_violations": baseline_violations,
        "artifacts": {
            "dictamen": {
                "present": bool(counts.get("has_dictamen")),
            },
            "hitos": counts.get("hitos", 0),
            "junta": counts.get("junta_items", 0),
            "candidates": {
                "sobre_1_tecnico": counts.get("sobre_1_tecnico", 0),
            },
            "compliance": counts.get("compliance") or {},
            "bases_committed": bool(counts.get("bases_committed")),
        },
        "last_rehydrate_error": state.get("rehydrate_last_error"),
        "last_rehydrate_success_at": state.get("rehydrate_last_success_at"),
    }

    try:
        from app.services.job_service import get_active_session_maintenance_job

        maint = get_active_session_maintenance_job(session_id)
        if maint:
            payload["maintenance_job"] = {
                "job_id": maint.get("job_id"),
                "status": maint.get("status"),
                "progress": maint.get("progress"),
            }
    except Exception:
        pass

    return payload
