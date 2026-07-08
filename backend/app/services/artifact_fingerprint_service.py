"""
Fingerprint de artefactos materializados (HRU R3).

Sidecar ``_LICITAI_FINGERPRINT.json`` por scope writer + registro en sesión.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "artifact_integrity_policy.json"


@lru_cache(maxsize=1)
def load_artifact_integrity_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_artifact_integrity_policy().get("policy_version") or "")


def sidecar_filename() -> str:
    return str(
        load_artifact_integrity_policy().get("sidecar_filename") or "_LICITAI_FINGERPRINT.json"
    )


def _hash_trunc_len() -> int:
    return int(load_artifact_integrity_policy().get("hash_truncated_hex_len") or 16)


def _economic_proposal_snapshot(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for task in reversed(list(session_state.get("tasks_completed") or [])):
        if not isinstance(task, dict):
            continue
        if str(task.get("task") or "") == "economic_proposal":
            res = task.get("result")
            return res if isinstance(res, dict) else None
    return None


def economic_snapshot_hash(snapshot: Optional[Dict[str, Any]]) -> str:
    if not snapshot:
        return ""
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[: _hash_trunc_len()]


def _bases_fingerprint(session_state: Dict[str, Any]) -> str:
    snap = session_state.get("bases_analysis_snapshot") or {}
    if isinstance(snap, dict):
        fp = str(snap.get("fingerprint") or "").strip()
        if fp:
            return fp
    return str(session_state.get("bases_analysis_fingerprint") or "").strip()


def build_fingerprint(
    session_state: Dict[str, Any],
    *,
    scope: str,
    company_id: Optional[str] = None,
    company_rfc: Optional[str] = None,
    generation_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Construye fingerprint determinista para un scope."""
    mp = session_state.get("master_profile") if isinstance(session_state.get("master_profile"), dict) else {}
    cid = str(company_id or session_state.get("company_id") or "").strip()
    rfc = str(company_rfc or mp.get("rfc") or "").strip().upper()
    snap = _economic_proposal_snapshot(session_state) if scope == "economic" else None
    return {
        "schema_version": str(load_artifact_integrity_policy().get("schema_version") or "artifact_fingerprint_v1"),
        "scope": scope,
        "company_id": cid or None,
        "company_rfc": rfc or None,
        "bases_fingerprint": _bases_fingerprint(session_state),
        "economic_snapshot_hash": economic_snapshot_hash(snap) if scope == "economic" else "",
        "generation_job_id": str(generation_job_id or "").strip() or None,
        "materialized_at": datetime.now(timezone.utc).isoformat(),
    }


def _scope_subdirs(scope: str) -> List[str]:
    scopes = load_artifact_integrity_policy().get("scopes") or {}
    cfg = scopes.get(scope) if isinstance(scopes, dict) else None
    if not isinstance(cfg, dict):
        return []
    return [str(s) for s in (cfg.get("output_subdirs") or []) if str(s).strip()]


def read_disk_fingerprint(session_output_path: str, scope: str) -> Optional[Dict[str, Any]]:
    """Lee sidecar fingerprint del primer subdir del scope que lo tenga."""
    sidecar = sidecar_filename()
    root = Path(session_output_path)
    if not root.is_dir():
        return None
    for sub in _scope_subdirs(scope):
        candidate = root / sub / sidecar
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else None
            except (OSError, json.JSONDecodeError):
                return None
    return None


def write_disk_fingerprint(
    session_output_path: str,
    scope: str,
    fingerprint: Dict[str, Any],
) -> Optional[str]:
    """
    Escribe sidecar bajo el primer subdir existente del scope (o lo crea).

    Returns:
        Ruta del sidecar escrito o None.
    """
    sidecar = sidecar_filename()
    root = Path(session_output_path)
    target_dir: Optional[Path] = None
    for sub in _scope_subdirs(scope):
        d = root / sub
        if d.is_dir():
            target_dir = d
            break
    if target_dir is None and _scope_subdirs(scope):
        target_dir = root / _scope_subdirs(scope)[0]
        target_dir.mkdir(parents=True, exist_ok=True)
    if target_dir is None:
        return None
    path = target_dir / sidecar
    path.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def fingerprint_matches(expected: Dict[str, Any], on_disk: Optional[Dict[str, Any]]) -> bool:
    if not on_disk:
        return False
    for key in ("company_id", "company_rfc", "economic_snapshot_hash"):
        exp = str(expected.get(key) or "").strip()
        if not exp:
            continue
        got = str(on_disk.get(key) or "").strip()
        if got and exp.upper() != got.upper():
            return False
    exp_bases = str(expected.get("bases_fingerprint") or "").strip()
    got_bases = str(on_disk.get("bases_fingerprint") or "").strip()
    if exp_bases and got_bases and exp_bases != got_bases:
        return False
    return True


def persist_session_fingerprint(
    session_state: Dict[str, Any],
    scope: str,
    fingerprint: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge fingerprint en ``session_state.artifact_fingerprints_v1``."""
    out = dict(session_state)
    store = dict(out.get("artifact_fingerprints_v1") or {})
    store[scope] = fingerprint
    out["artifact_fingerprints_v1"] = store
    return out


def disk_fingerprint_matches_session(
    session_output_path: str,
    session_state: Dict[str, Any],
    *,
    scope: str,
) -> bool:
    """True si disco tiene sidecar que coincide con fingerprint esperado de sesión."""
    expected = build_fingerprint(session_state, scope=scope)
    on_disk = read_disk_fingerprint(session_output_path, scope)
    return fingerprint_matches(expected, on_disk)


def scopes_with_fingerprint_mismatch(
    session_output_path: str,
    session_state: Dict[str, Any],
    *,
    scopes: Optional[List[str]] = None,
) -> List[str]:
    """
    Scopes con archivos entregables pero fingerprint ausente o distinto.
    """
    from app.services.generation_wipe_policy import count_deliverable_files_under

    check = scopes or list((load_artifact_integrity_policy().get("scopes") or {}).keys())
    mismatched: List[str] = []
    for scope in check:
        subdirs = _scope_subdirs(str(scope))
        if count_deliverable_files_under(session_output_path, subdirs) <= 0:
            continue
        if not disk_fingerprint_matches_session(session_output_path, session_state, scope=str(scope)):
            mismatched.append(str(scope))
    return mismatched


async def materialize_economic_fingerprint(
    memory: Any,
    session_id: str,
    session_state: Dict[str, Any],
    *,
    session_output_path: Optional[str] = None,
    generation_job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Escribe fingerprint económico en disco y persiste en sesión tras writer exitoso.
    """
    output_path = session_output_path or os.path.join("/data/outputs", session_id)
    fp = build_fingerprint(
        session_state,
        scope="economic",
        generation_job_id=generation_job_id,
    )
    sidecar_path = write_disk_fingerprint(output_path, "economic", fp)
    patched = persist_session_fingerprint(session_state, "economic", fp)
    await memory.save_session(session_id, {"artifact_fingerprints_v1": patched.get("artifact_fingerprints_v1")})
    return {"fingerprint": fp, "sidecar_path": sidecar_path}
