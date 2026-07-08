"""
Política HRU de wipe pre-generación (PR2 / P1.1).

Evita borrar artefactos válidos cuando un job quedó ``blocked`` pero ya hay
archivos en disco para ese alcance. Sin reglas por licitación.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from app.services.delivery_scope_policy import include_directories_for_scope
from app.services.generation_concurrency_controller import (
    preserve_subdirs_for_active_streams,
)
from app.services.generation_mode_policy import (
    active_jobs_for_mode,
    load_generation_mode_policy,
    wipe_preserve_subdirs_for_mode,
)


def _wipe_behavior_cfg() -> Dict[str, Any]:
    raw = load_generation_mode_policy().get("wipe_behavior")
    return raw if isinstance(raw, dict) else {}


def force_regenerate_requested(company_data: Optional[Dict[str, Any]]) -> bool:
    """True si el cliente pidió regeneración forzada vía clave en policy."""
    key = str(_wipe_behavior_cfg().get("force_regenerate_company_data_key") or "force_regenerate")
    if not isinstance(company_data, dict):
        return False
    return bool(company_data.get(key))


def output_subdirs_for_writer_job(job_id: str) -> List[str]:
    """Subcarpetas de salida asociadas a un job de escritura (desde alcance F5)."""
    jid = str(job_id or "").strip().lower()
    if jid == "economic_writer":
        return list(include_directories_for_scope("economic"))
    if jid in ("technical", "formats"):
        tech_dirs = set(include_directories_for_scope("technical"))
        if jid == "formats":
            return [d for d in tech_dirs if "administrativ" in d.lower()]
        return [d for d in tech_dirs if "administrativ" not in d.lower()] or list(tech_dirs)
    return []


def count_deliverable_files_under(session_output_path: str, subdirs: List[str]) -> int:
    """Cuenta archivos con extensión de entrega bajo subcarpetas indicadas."""
    from app.services.delivery_scope_policy import allowed_delivery_extensions

    if not session_output_path or not os.path.isdir(session_output_path):
        return 0
    allowed = allowed_delivery_extensions()
    total = 0
    for sub in subdirs:
        base = os.path.join(session_output_path, sub)
        if not os.path.isdir(base):
            continue
        for root, _, files in os.walk(base):
            for name in files:
                low = name.lower()
                if any(low.endswith(ext) for ext in allowed):
                    total += 1
    return total


def _job_status(gen_state: Optional[Dict[str, Any]], job_id: str) -> str:
    if not isinstance(gen_state, dict):
        return ""
    jobs = gen_state.get("jobs")
    if not isinstance(jobs, list):
        return ""
    for j in jobs:
        if isinstance(j, dict) and str(j.get("id") or "") == job_id:
            return str(j.get("status") or "").strip().lower()
    return ""


def evaluate_pre_generation_wipe(
    *,
    generation_mode: str,
    gen_state: Optional[Dict[str, Any]],
    session_output_path: Optional[str],
    company_data: Optional[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Decide si ejecutar wipe selectivo antes de los writers.

    Returns:
        dict con ``should_wipe`` (bool) y ``reason`` (str estable para logs).
    """
    if force_regenerate_requested(company_data):
        return {"should_wipe": True, "reason": "force_regenerate"}

    if not session_output_path or not os.path.isdir(session_output_path):
        return {"should_wipe": True, "reason": "no_output_dir"}

    active = active_jobs_for_mode(generation_mode)
    writer_jobs = ("technical", "formats", "economic_writer")
    job_scope = {
        "economic_writer": "economic",
        "technical": "technical",
        "formats": "admin",
    }

    from app.services.artifact_fingerprint_service import (
        disk_fingerprint_matches_session,
        load_artifact_integrity_policy,
        scopes_with_fingerprint_mismatch,
    )

    integrity = load_artifact_integrity_policy()

    if session_state and bool(integrity.get("wipe_on_mismatch", True)):
        scopes = [job_scope[j] for j in writer_jobs if j in active and j in job_scope]
        mismatched = scopes_with_fingerprint_mismatch(
            session_output_path,
            session_state,
            scopes=scopes,
        )
        if mismatched:
            return {
                "should_wipe": True,
                "reason": "artifact_fingerprint_mismatch",
                "mismatched_scopes": mismatched,
            }

    preserve_blocked = bool(_wipe_behavior_cfg().get("preserve_artifacts_when_job_blocked", True))
    preserve_only_match = bool(integrity.get("preserve_blocked_only_when_fingerprint_matches", True))

    if preserve_blocked:
        for job_id in writer_jobs:
            if job_id not in active:
                continue
            if _job_status(gen_state, job_id) != "blocked":
                continue
            dirs = output_subdirs_for_writer_job(job_id)
            if count_deliverable_files_under(session_output_path, dirs) <= 0:
                continue
            scope = job_scope.get(job_id)
            if (
                preserve_only_match
                and scope
                and session_state
                and disk_fingerprint_matches_session(session_output_path, session_state, scope=scope)
            ):
                return {
                    "should_wipe": False,
                    "reason": "blocked_job_preserves_artifacts",
                    "preserved_job_id": job_id,
                    "artifact_count_hint": count_deliverable_files_under(session_output_path, dirs),
                }
            if not preserve_only_match:
                return {
                    "should_wipe": False,
                    "reason": "blocked_job_preserves_artifacts",
                    "preserved_job_id": job_id,
                    "artifact_count_hint": count_deliverable_files_under(session_output_path, dirs),
                }

    return {"should_wipe": True, "reason": "standard_pre_generation"}


def combined_wipe_preserve_subdirs(
    generation_mode: str,
    gen_state: Optional[Dict[str, Any]],
) -> List[str]:
    """Subcarpetas a preservar en wipe: modo F2 + streams activos F6."""
    base = list(wipe_preserve_subdirs_for_mode(generation_mode))
    extra = preserve_subdirs_for_active_streams(gen_state)
    seen: Set[str] = set()
    out: List[str] = []
    for sub in base + extra:
        key = sub.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(sub)
    return out


def subdirs_targeted_by_wipe(generation_mode: str) -> List[str]:
    """Subcarpetas que el wipe selectivo eliminaría para un modo (informativo)."""
    preserve: Set[str] = {s.lower() for s in wipe_preserve_subdirs_for_mode(generation_mode)}
    if not preserve:
        return []
    all_dirs: Set[str] = set()
    for scope in ("technical", "economic", "full"):
        for d in include_directories_for_scope(scope):
            all_dirs.add(d)
    return [d for d in sorted(all_dirs) if d.lower() not in preserve]
