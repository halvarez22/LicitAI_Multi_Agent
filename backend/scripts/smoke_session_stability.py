#!/usr/bin/env python3
"""
Smoke de estabilidad por sesión: HITL, artefactos de análisis y checklist sin recursión.

Uso:
  PYTHONPATH=/app python scripts/smoke_session_stability.py
  PYTHONPATH=/app python scripts/smoke_session_stability.py --session vigilancia_issste
  PYTHONPATH=/app python scripts/smoke_session_stability.py --min-hitos 1

Exit codes:
  0 — OK
  1 — WARN (artefactos incompletos, pending_reanalysis, etc.)
  2 — FAIL (sesión ausente, RecursionError o checklist > umbral de tiempo)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_SESSIONS = (
    "isapeg_servicios_de_limpieza",
    "unaq-2026_paneles_solares",
    "vigilancia_issste",
)

CHECKLIST_TIME_LIMIT_S = 5.0
MIN_JUNTA_ITEMS = 1
MIN_SOBRE_TECNICO = 1


def _cronograma_from_analysis(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from app.checklist.submission_checklist_service import _cronograma_from_analysis_result

    for t in reversed(state.get("tasks_completed") or []):
        if isinstance(t, dict) and t.get("task") == "stage_completed:analysis":
            return _cronograma_from_analysis_result(t.get("result"))
    return None


def count_hitos(state: Dict[str, Any]) -> int:
    block = state.get("submission_checklist") or {}
    hitos = block.get("hitos") if isinstance(block, dict) else None
    return len(hitos) if isinstance(hitos, list) else 0


def count_junta_items(state: Dict[str, Any]) -> int:
    bundle = state.get("junta_aclaraciones_questions") or {}
    if not isinstance(bundle, dict):
        return 0
    summary = bundle.get("summary") or {}
    if isinstance(summary, dict) and summary.get("total") is not None:
        try:
            return int(summary["total"])
        except (TypeError, ValueError):
            pass
    items = bundle.get("items") or []
    return len(items) if isinstance(items, list) else 0


def count_sobre_tecnico(state: Dict[str, Any]) -> int:
    cand = (
        state.get("document_candidates_consolidated")
        or state.get("document_candidates_final")
        or state.get("document_candidates_v1")
    )
    if not isinstance(cand, dict):
        return 0
    sobre = cand.get("sobre_1_tecnico") or []
    return len(sobre) if isinstance(sobre, list) else 0


def checklist_at_risk(state: Dict[str, Any]) -> bool:
    """Checklist persistido sin cronograma en stage_completed:analysis (patrón VIGILANCIA)."""
    return count_hitos(state) > 0 and _cronograma_from_analysis(state) is None


async def run_checklist_smoke(
    memory: Any,
    session_id: str,
    *,
    time_limit_s: float = CHECKLIST_TIME_LIMIT_S,
) -> Tuple[bool, Optional[str], float]:
    """
    Ejecuta ensure_session_cronograma_and_checklist midiendo tiempo.

    Returns:
        (ok, fatal_error, elapsed_seconds)
        fatal_error: ``recursion`` | ``timeout`` | None
    """
    from app.checklist.submission_checklist_service import (
        ensure_session_cronograma_and_checklist,
    )

    t0 = time.perf_counter()
    try:
        await ensure_session_cronograma_and_checklist(memory, session_id)
    except RecursionError:
        return False, "recursion", time.perf_counter() - t0
    elapsed = time.perf_counter() - t0
    if elapsed > time_limit_s:
        return False, "timeout", elapsed
    return True, None, elapsed


def evaluate_artifact_blockers(
    state: Dict[str, Any],
    *,
    min_hitos: int,
    min_junta: int = MIN_JUNTA_ITEMS,
    min_sobre: int = MIN_SOBRE_TECNICO,
    require_dictamen: bool = True,
) -> List[str]:
    """Reglas P2-01 sobre artefactos persistidos."""
    blockers: List[str] = []
    has_cml = isinstance(state.get("compliance_master_list"), dict) and any(
        (state.get("compliance_master_list") or {}).get(z)
        for z in ("administrativo", "tecnico", "formatos")
    )

    n_hitos = count_hitos(state)
    if n_hitos < min_hitos:
        blockers.append(f"hitos_below_min:{n_hitos}<{min_hitos}")

    n_junta = count_junta_items(state)
    if n_junta < min_junta:
        blockers.append(f"junta_below_min:{n_junta}<{min_junta}")

    if require_dictamen and not state.get("dictamen"):
        blockers.append("dictamen_missing")

    if has_cml:
        n_sobre = count_sobre_tecnico(state)
        if n_sobre < min_sobre:
            blockers.append(f"candidates_sobre_tecnico_below_min:{n_sobre}<{min_sobre}")

    return blockers


async def inspect_session(
    session_id: str,
    *,
    min_hitos: int = 6,
    checklist_time_limit_s: float = CHECKLIST_TIME_LIMIT_S,
) -> Dict[str, Any]:
    from app.api.deps import get_connected_memory
    from app.services.session_bases_analysis_invalidation import bases_analysis_committed

    memory = await get_connected_memory()
    fatal_errors: List[str] = []
    try:
        state = await memory.get_session(session_id) or {}
        if not state:
            return {
                "session_id": session_id,
                "verdict": "MISSING",
                "blockers": ["session_not_found"],
                "fatal_errors": [],
            }

        snap = state.get("bases_analysis_snapshot") or {}
        pending = list(state.get("pending_questions") or [])
        eco_inputs = state.get("economic_user_inputs") or {}
        gen = state.get("generation_state") or {}
        jobs = gen.get("jobs") or [] if isinstance(gen, dict) else []
        blocked_jobs = [
            j.get("id")
            for j in jobs
            if isinstance(j, dict) and str(j.get("status") or "").lower() in ("blocked", "error")
        ]

        line_items: List[Dict[str, Any]] = []
        try:
            line_items = await memory.get_line_items_for_session(session_id) or []
        except Exception:
            pass

        cml = state.get("compliance_master_list") or {}
        cml_counts = {
            k: len(v or [])
            for k, v in cml.items()
            if isinstance(v, list)
        } if isinstance(cml, dict) else {}

        blockers: List[str] = []
        if snap.get("pending_reanalysis"):
            blockers.append("bases_pending_reanalysis")
        if not state.get("compliance_master_list") and bases_analysis_committed(state):
            blockers.append("compliance_missing_after_commit")

        at_risk = checklist_at_risk(state)
        cl_ok, cl_fatal, cl_elapsed = await run_checklist_smoke(
            memory,
            session_id,
            time_limit_s=checklist_time_limit_s,
        )
        if cl_fatal == "recursion":
            fatal_errors.append("checklist_recursion")
        elif cl_fatal == "timeout":
            fatal_errors.append(f"checklist_timeout:{cl_elapsed:.2f}s")
        elif not cl_ok:
            fatal_errors.append("checklist_failed")

        state = await memory.get_session(session_id) or state
        blockers.extend(
            evaluate_artifact_blockers(state, min_hitos=min_hitos)
        )

        if fatal_errors:
            verdict = "FAIL"
        elif blockers:
            verdict = "WARN"
        else:
            verdict = "OK"

        return {
            "session_id": session_id,
            "verdict": verdict,
            "blockers": blockers,
            "fatal_errors": fatal_errors,
            "bases_committed": bases_analysis_committed(state),
            "pending_questions": len(pending),
            "economic_user_inputs_keys": len(eco_inputs) if isinstance(eco_inputs, dict) else 0,
            "session_line_items": len(line_items),
            "generation_status": gen.get("status") if isinstance(gen, dict) else None,
            "generation_blocked_jobs": blocked_jobs,
            "compliance_counts": cml_counts,
            "stop_reason": (state.get("last_orchestrator_decision") or {}).get("stop_reason"),
            "artifacts": {
                "hitos": count_hitos(state),
                "junta_items": count_junta_items(state),
                "sobre_1_tecnico": count_sobre_tecnico(state),
                "has_dictamen": bool(state.get("dictamen")),
                "checklist_at_risk": at_risk,
                "checklist_elapsed_s": round(cl_elapsed, 3),
            },
        }
    finally:
        await memory.disconnect()


async def main() -> None:
    ap = argparse.ArgumentParser(description="Smoke estabilidad sesiones referencia")
    ap.add_argument("--session", action="append", dest="sessions", default=[])
    ap.add_argument(
        "--min-hitos",
        type=int,
        default=6,
        help="Mínimo de hitos esperados (6 referencia; 1 sesión nueva)",
    )
    ap.add_argument(
        "--checklist-timeout",
        type=float,
        default=CHECKLIST_TIME_LIMIT_S,
        help="Segundos máximos para ensure_session_cronograma_and_checklist",
    )
    args = ap.parse_args()
    targets = args.sessions or list(DEFAULT_SESSIONS)
    results = []
    for sid in targets:
        results.append(
            await inspect_session(
                sid,
                min_hitos=args.min_hitos,
                checklist_time_limit_s=args.checklist_timeout,
            )
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))

    if any(r.get("verdict") == "MISSING" for r in results):
        sys.exit(2)
    if any(r.get("fatal_errors") for r in results):
        sys.exit(2)
    if any(r.get("verdict") == "WARN" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
