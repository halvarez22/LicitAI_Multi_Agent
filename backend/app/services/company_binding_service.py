"""
Ligado transaccional de empresa a sesión (HRU R2).

Fuente normativa: ``company_binding_policy.json``.
"""

from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.expediente_readiness_service import resolve_expediente_readiness

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "company_binding_policy.json"


@lru_cache(maxsize=1)
def load_company_binding_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_company_binding_policy().get("policy_version") or "")


def _profile_rfc(profile: Optional[Dict[str, Any]]) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("rfc") or "").strip().upper()


def _invalidation_rules(*, company_changed: bool) -> Dict[str, Any]:
    policy = load_company_binding_policy()
    key = (
        "invalidate_on_company_change"
        if company_changed
        else "invalidate_on_profile_refresh_same_company"
    )
    rules = policy.get(key) if isinstance(policy.get(key), dict) else {}
    return rules if isinstance(rules, dict) else {}


def _remove_tasks(session_state: Dict[str, Any], task_names: List[str]) -> int:
    exact = frozenset(str(t) for t in task_names)
    tasks = list(session_state.get("tasks_completed") or [])
    if not tasks:
        return 0
    kept: List[Dict[str, Any]] = []
    removed = 0
    for t in tasks:
        if not isinstance(t, dict):
            kept.append(t)
            continue
        if str(t.get("task") or "") in exact:
            removed += 1
            continue
        kept.append(t)
    session_state["tasks_completed"] = kept
    return removed


def _clear_session_keys(session_state: Dict[str, Any], keys: List[str]) -> List[str]:
    cleared: List[str] = []
    for key in keys:
        k = str(key)
        if k in session_state:
            session_state.pop(k, None)
            cleared.append(k)
    return cleared


def _reset_generation_jobs(session_state: Dict[str, Any], job_ids: List[str]) -> List[str]:
    reset: List[str] = []
    gen = session_state.get("generation_state")
    if not isinstance(gen, dict):
        return reset
    jobs = gen.get("jobs")
    if not isinstance(jobs, list):
        return reset
    targets = frozenset(str(j) for j in job_ids)
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id") or "")
        if jid in targets and str(job.get("status") or "") in ("done", "blocked", "error", "resumed"):
            job["status"] = "pending"
            reset.append(jid)
    if reset:
        gen["status"] = "pending"
        session_state["generation_state"] = gen
    return reset


def wipe_output_subdirs(session_path: str, subdirs: List[str]) -> Tuple[int, List[str]]:
    """
    Elimina subcarpetas concretas bajo la raíz de outputs de sesión.

    Returns:
        (conteo eliminado, nombres eliminados)
    """
    if not session_path or not os.path.isdir(session_path):
        return 0, []
    removed: List[str] = []
    for sub in subdirs:
        name = str(sub or "").strip()
        if not name:
            continue
        full = os.path.join(session_path, name)
        if not os.path.exists(full):
            continue
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            removed.append(name)
        except OSError:
            raise
    return len(removed), removed


def _company_changed(
    session_state: Dict[str, Any],
    *,
    new_company_id: str,
    new_profile: Dict[str, Any],
) -> bool:
    old_id = str(session_state.get("company_id") or "").strip()
    if old_id and old_id != new_company_id:
        return True
    old_mp = session_state.get("master_profile")
    old_rfc = _profile_rfc(old_mp if isinstance(old_mp, dict) else None)
    new_rfc = _profile_rfc(new_profile)
    return bool(old_rfc and new_rfc and old_rfc != new_rfc)


def apply_company_binding_patch(
    session_state: Dict[str, Any],
    *,
    company_id: str,
    master_profile: Dict[str, Any],
    company_changed: bool,
) -> Dict[str, Any]:
    """
    Aplica parches de sesión por ligado de empresa (sin persistir ni tocar disco).

    Returns:
        Resumen de invalidaciones aplicadas.
    """
    rules = _invalidation_rules(company_changed=company_changed)
    out = dict(session_state)
    out["company_id"] = company_id
    out["master_profile"] = dict(master_profile)

    tasks_removed = _remove_tasks(out, list(rules.get("tasks_remove_exact") or []))
    keys_cleared = _clear_session_keys(out, list(rules.get("session_keys_clear") or []))
    jobs_reset = _reset_generation_jobs(out, list(rules.get("generation_jobs_reset_to_pending") or []))

    out.setdefault("company_binding_v1", {})
    if isinstance(out["company_binding_v1"], dict):
        from datetime import datetime, timezone

        out["company_binding_v1"] = {
            **out["company_binding_v1"],
            "company_id": company_id,
            "company_rfc": _profile_rfc(master_profile),
            "bound_at": datetime.now(timezone.utc).isoformat(),
            "company_changed": company_changed,
        }

    return {
        "session_patch": out,
        "company_changed": company_changed,
        "tasks_removed": tasks_removed,
        "keys_cleared": keys_cleared,
        "jobs_reset": jobs_reset,
    }


async def bind_company_to_session(
    memory: Any,
    session_id: str,
    company_id: str,
    *,
    session_output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Liga una empresa válida del catálogo a la sesión e invalida artefactos incoherentes.

    Args:
        memory: Repositorio con ``get_session``, ``save_session``, ``get_company``.
        session_id: ID de sesión.
        company_id: ID de empresa en catálogo.
        session_output_path: Raíz opcional de outputs; si None se resuelve bajo ``/data/outputs``.

    Returns:
        dict con ``success``, ``binding_summary``, ``readiness`` y errores estables.

    Raises:
        ValueError: con ``error_type`` estable en el mensaje para casos de negocio.
    """
    policy = load_company_binding_policy()
    errors = policy.get("error_types") if isinstance(policy.get("error_types"), dict) else {}

    cid = str(company_id or "").strip()
    if not cid:
        raise ValueError(str(errors.get("COMPANY_ID_REQUIRED") or "COMPANY_ID_REQUIRED"))

    session = await memory.get_session(session_id)
    if not session:
        raise ValueError(str(errors.get("SESSION_NOT_FOUND") or "SESSION_NOT_FOUND"))

    company = await memory.get_company(cid)
    if not company:
        raise ValueError(str(errors.get("COMPANY_NOT_FOUND") or "COMPANY_NOT_FOUND"))

    master_profile = company.get("master_profile") if isinstance(company.get("master_profile"), dict) else {}
    if not master_profile:
        master_profile = {
            "razon_social": company.get("name"),
            "rfc": (company.get("master_profile") or {}).get("rfc") if isinstance(company.get("master_profile"), dict) else None,
        }

    changed = _company_changed(session, new_company_id=cid, new_profile=master_profile)
    patch_result = apply_company_binding_patch(
        dict(session),
        company_id=cid,
        master_profile=master_profile,
        company_changed=changed,
    )
    updated_session = patch_result["session_patch"]

    wipe_summary: Dict[str, Any] = {"removed_count": 0, "removed_names": []}
    rules = _invalidation_rules(company_changed=changed)
    subdirs = [str(s) for s in (rules.get("wipe_output_subdirs") or []) if str(s).strip()]
    if subdirs:
        output_path = session_output_path
        if not output_path:
            try:
                from app.api.v1.routes.downloads import resolve_outputs_root

                output_path = await resolve_outputs_root(session_id)
            except Exception:
                output_path = os.path.join("/data/outputs", session_id)
        if output_path and os.path.isdir(output_path):
            n, names = wipe_output_subdirs(output_path, subdirs)
            wipe_summary = {"removed_count": n, "removed_names": names, "output_dir": output_path}

    await memory.save_session(session_id, updated_session)

    readiness = resolve_expediente_readiness(
        {**updated_session, "session_id": session_id},
        company_profile=master_profile,
        company_exists=True,
        session_output_path=wipe_summary.get("output_dir") if wipe_summary.get("output_dir") else session_output_path,
    )

    return {
        "success": True,
        "session_id": session_id,
        "company_id": cid,
        "company_rfc": _profile_rfc(master_profile),
        "company_label": str(master_profile.get("razon_social") or company.get("name") or ""),
        "company_changed": changed,
        "invalidation": {
            "tasks_removed": patch_result["tasks_removed"],
            "keys_cleared": patch_result["keys_cleared"],
            "jobs_reset": patch_result["jobs_reset"],
            "disk_wipe": wipe_summary,
        },
        "readiness": readiness,
    }


async def ensure_company_bound_for_generation(
    memory: Any,
    session_id: str,
    company_id: str,
    session_state: Dict[str, Any],
    *,
    session_output_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Asegura ligado coherente antes de generación.

    Si ``company_id`` difiere del persistido o el RFC de sesión no coincide con DB,
    ejecuta ``bind_company_to_session`` (con wipe económico si cambió empresa).

    Returns:
        Resultado de bind si se aplicó; None si ya estaba ligado correctamente.
    """
    cid = str(company_id or "").strip()
    if not cid:
        return None

    company = await memory.get_company(cid)
    if not company:
        raise ValueError("COMPANY_NOT_FOUND")

    master_profile = company.get("master_profile") if isinstance(company.get("master_profile"), dict) else {}
    session_cid = str(session_state.get("company_id") or "").strip()
    needs_bind = session_cid != cid or _company_changed(
        session_state,
        new_company_id=cid,
        new_profile=master_profile,
    )
    if not needs_bind:
        session_mp = session_state.get("master_profile")
        if isinstance(session_mp, dict) and _profile_rfc(session_mp) != _profile_rfc(master_profile):
            needs_bind = True

    if not needs_bind:
        return None

    return await bind_company_to_session(
        memory,
        session_id,
        cid,
        session_output_path=session_output_path,
    )
