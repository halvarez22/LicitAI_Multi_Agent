"""
Controlador HRU de concurrencia dual-stream (F6 / ADR-001).

Gestiona locks por stream (técnico / económico) en una misma sesión.
Fuente canónica: ``app/contracts/generation_concurrency_policy.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config.settings import settings
from app.services.delivery_scope_policy import include_directories_for_scope
from app.services.generation_mode_policy import decoupled_generation_enabled, normalize_generation_mode

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "generation_concurrency_policy.json"
)

_STREAM_IDS = ("technical", "economic", "shared")


@dataclass(frozen=True)
class StreamLockResult:
    """Resultado de intento de adquisición de lock por stream."""

    acquired: bool
    reason: str = ""
    holder_job_id: Optional[str] = None


@lru_cache(maxsize=1)
def load_generation_concurrency_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_generation_concurrency_policy().get("policy_version") or "")


def dual_stream_enabled() -> bool:
    """True si F6 dual-stream está habilitado (requiere desacople F2)."""
    if not decoupled_generation_enabled():
        return False
    return bool(getattr(settings, "DUAL_STREAM_ENABLED", True))


def normalize_stream_id(raw: Optional[str]) -> str:
    policy = load_generation_concurrency_policy()
    aliases = policy.get("aliases") if isinstance(policy.get("aliases"), dict) else {}
    token = str(raw or "").strip().lower()
    if not token:
        return "full"
    if token in aliases:
        token = str(aliases[token]).strip().lower()
    if token in _STREAM_IDS or token == "full":
        return token
    return "full"


def stream_for_job(job_id: str) -> str:
    """Mapea job_id → stream (technical | economic | shared)."""
    jid = str(job_id or "").strip()
    policy = load_generation_concurrency_policy()
    streams = policy.get("streams")
    if isinstance(streams, dict):
        for stream_id, cfg in streams.items():
            if not isinstance(cfg, dict):
                continue
            job_ids = cfg.get("job_ids") or []
            if jid in job_ids:
                return str(stream_id)
    return "shared"


def job_ids_for_stream(stream_id: str) -> Tuple[str, ...]:
    policy = load_generation_concurrency_policy()
    streams = policy.get("streams")
    if not isinstance(streams, dict):
        return tuple()
    cfg = streams.get(stream_id)
    if not isinstance(cfg, dict):
        return tuple()
    return tuple(str(j) for j in (cfg.get("job_ids") or []) if str(j).strip())


def resolve_generation_stream_from_input(
    input_data: Optional[Dict[str, Any]],
    generation_mode: str,
) -> str:
    """
    Cascada HRU: request explícito > company_data > modo de generación > full.
    """
    data = input_data if isinstance(input_data, dict) else {}
    company = data.get("company_data") if isinstance(data.get("company_data"), dict) else {}

    for candidate in (
        data.get("generation_stream"),
        company.get("generation_stream"),
    ):
        if candidate:
            return normalize_stream_id(str(candidate))

    mode = normalize_generation_mode(generation_mode)
    policy = load_generation_concurrency_policy()
    defaults = policy.get("generation_mode_default_stream")
    if isinstance(defaults, dict) and mode in defaults:
        return normalize_stream_id(str(defaults[mode]))
    return "full"


def writable_subdirs_for_stream(stream_id: str) -> List[str]:
    """Subcarpetas de salida asociadas a un stream (vía delivery_scope_policy)."""
    policy = load_generation_concurrency_policy()
    streams = policy.get("streams")
    if not isinstance(streams, dict):
        return []
    cfg = streams.get(stream_id)
    if not isinstance(cfg, dict):
        return []
    scope = str(cfg.get("writable_scope") or "").strip().lower()
    if not scope:
        return []
    return list(include_directories_for_scope(scope))


def _stream_cfg(stream_id: str) -> Dict[str, Any]:
    streams = load_generation_concurrency_policy().get("streams")
    if not isinstance(streams, dict):
        return {}
    cfg = streams.get(stream_id)
    return cfg if isinstance(cfg, dict) else {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_streams_state() -> Dict[str, Any]:
    return {
        "technical": {
            "status": "idle",
            "generation_mode": "technical",
            "jobs": [],
            "lock": None,
        },
        "economic": {
            "status": "idle",
            "generation_mode": "economic",
            "jobs": [],
            "lock": None,
        },
        "shared": {
            "status": "idle",
            "generation_mode": "full",
            "jobs": [],
            "lock": None,
        },
    }


def ensure_streams_structure(gen_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Garantiza ``generation_state.streams`` con estructura F6."""
    base = dict(gen_state) if isinstance(gen_state, dict) else {}
    streams = base.get("streams")
    if not isinstance(streams, dict):
        streams = default_streams_state()
    else:
        merged = default_streams_state()
        for key in _STREAM_IDS:
            raw = streams.get(key)
            if isinstance(raw, dict):
                merged[key] = {**merged[key], **raw}
        streams = merged
    base["streams"] = streams
    return base


def is_stream_running(gen_state: Optional[Dict[str, Any]], stream_id: str) -> bool:
    if not isinstance(gen_state, dict):
        return False
    streams = gen_state.get("streams")
    if not isinstance(streams, dict):
        return False
    stream = streams.get(stream_id)
    if not isinstance(stream, dict):
        return False
    if str(stream.get("status") or "").lower() == "running":
        return True
    lock = stream.get("lock")
    return isinstance(lock, dict) and bool(lock.get("holder_job_id"))


def stream_lock_holder(gen_state: Optional[Dict[str, Any]], stream_id: str) -> Optional[str]:
    if not isinstance(gen_state, dict):
        return None
    streams = gen_state.get("streams")
    if not isinstance(streams, dict):
        return None
    stream = streams.get(stream_id)
    if not isinstance(stream, dict):
        return None
    lock = stream.get("lock")
    if not isinstance(lock, dict):
        return None
    holder = lock.get("holder_job_id")
    return str(holder) if holder else None


def try_acquire_stream_lock(
    gen_state: Dict[str, Any],
    stream_id: str,
    job_id: str,
) -> StreamLockResult:
    """
    Adquiere lock del stream si está libre o ya lo posee el mismo job_id.

    Streams ``technical`` y ``economic`` pueden coexistir; el mismo stream no.
    """
    if not dual_stream_enabled() or stream_id in ("full", "shared"):
        return StreamLockResult(acquired=True, reason="dual_stream_off_or_shared")

    state = ensure_streams_structure(gen_state)
    gen_state.clear()
    gen_state.update(state)

    stream = gen_state["streams"][stream_id]
    lock = stream.get("lock")
    holder = None
    if isinstance(lock, dict):
        holder = lock.get("holder_job_id")

    if holder and str(holder) != str(job_id):
        return StreamLockResult(
            acquired=False,
            reason="stream_already_running",
            holder_job_id=str(holder),
        )

    stream["lock"] = {"holder_job_id": str(job_id), "since": _utc_now_iso()}
    stream["status"] = "running"
    return StreamLockResult(acquired=True, reason="acquired")


def release_stream_lock(
    gen_state: Optional[Dict[str, Any]],
    stream_id: str,
    job_id: str,
) -> None:
    """Libera lock si el job_id coincide."""
    if not isinstance(gen_state, dict) or stream_id in ("full",):
        return
    streams = gen_state.get("streams")
    if not isinstance(streams, dict):
        return
    stream = streams.get(stream_id)
    if not isinstance(stream, dict):
        return
    lock = stream.get("lock")
    if not isinstance(lock, dict):
        return
    if str(lock.get("holder_job_id") or "") != str(job_id):
        return
    stream["lock"] = None
    if str(stream.get("status") or "").lower() == "running":
        stream["status"] = "idle"


def streams_blocking_shared(gen_state: Optional[Dict[str, Any]]) -> List[str]:
    """Streams que impiden ejecutar packager/delivery por política."""
    if not isinstance(gen_state, dict):
        return []
    cfg = _stream_cfg("shared")
    required_idle = cfg.get("requires_idle_streams") or []
    blocking: List[str] = []
    for sid in required_idle:
        if is_stream_running(gen_state, str(sid)):
            blocking.append(str(sid))
    return blocking


def preserve_subdirs_for_active_streams(gen_state: Optional[Dict[str, Any]]) -> List[str]:
    """Subcarpetas a preservar en wipe cuando un stream hermano está activo."""
    if not dual_stream_enabled() or not isinstance(gen_state, dict):
        return []
    preserved: Set[str] = set()
    for stream_id in ("technical", "economic"):
        if is_stream_running(gen_state, stream_id):
            for sub in writable_subdirs_for_stream(stream_id):
                preserved.add(sub)
    return sorted(preserved)


def active_stream_ids(gen_state: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(gen_state, dict):
        return []
    out: List[str] = []
    for stream_id in ("technical", "economic"):
        if is_stream_running(gen_state, stream_id):
            out.append(stream_id)
    return out


def merge_stream_generation_state(
    existing: Optional[Dict[str, Any]],
    stream_id: str,
    stream_patch: Dict[str, Any],
    *,
    generation_mode: str,
    flat_jobs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Fusiona actualización de un stream sin pisar el stream hermano (concurrencia F6).
    """
    merged = ensure_streams_structure(existing)
    streams = merged["streams"]
    prev = streams.get(stream_id) if isinstance(streams.get(stream_id), dict) else {}
    streams[stream_id] = {**prev, **stream_patch}
    merged["generation_mode"] = normalize_generation_mode(generation_mode)
    merged["jobs"] = list(flat_jobs)
    active = active_stream_ids(merged)
    merged["active_streams"] = active
    if active:
        merged["status"] = "running"
    elif str(merged.get("status") or "") == "running":
        merged["status"] = "idle"
    return merged
