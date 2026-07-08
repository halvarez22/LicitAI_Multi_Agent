"""
Controlador HRU de cola ``generation_state`` por modo de generación (F2) y stream (F6).

Marca jobs ``skipped`` según política versionada; soporta colas anidadas por stream
con vista plana ``jobs`` para compatibilidad legacy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.generation_concurrency_controller import (
    default_streams_state,
    dual_stream_enabled,
    ensure_streams_structure,
    job_ids_for_stream,
    merge_stream_generation_state,
    stream_for_job,
)
from app.services.generation_mode_policy import (
    active_jobs_for_mode,
    normalize_generation_mode,
    skipped_jobs_for_mode,
)


def _default_generation_jobs() -> List[Dict[str, Any]]:
    return [
        {"id": "datagap", "type": "checkpoint", "status": "pending"},
        {"id": "technical", "type": "agent", "status": "pending"},
        {"id": "formats", "type": "agent", "status": "pending"},
        {"id": "economic_writer", "type": "agent", "status": "pending"},
        {"id": "packager", "type": "agent", "status": "pending"},
        {"id": "delivery", "type": "agent", "status": "pending"},
    ]


def _default_jobs_for_stream(stream_id: str) -> List[Dict[str, Any]]:
    """Jobs iniciales para un stream F6."""
    all_jobs = {j["id"]: dict(j) for j in _default_generation_jobs()}
    ids = job_ids_for_stream(stream_id)
    if not ids:
        return _default_generation_jobs()
    return [all_jobs[jid] for jid in ids if jid in all_jobs]


def _flatten_and_apply_mode_respecting_parallel_streams(
    gen_state: Dict[str, Any],
    generation_mode: str,
) -> List[Dict[str, Any]]:
    """
    Vista plana con skips del modo actual, pero sin pisar jobs de streams hermanos activos.
    """
    from app.services.generation_concurrency_controller import is_stream_running, stream_for_job

    flat = apply_generation_mode_to_jobs(flatten_jobs_from_streams(gen_state), generation_mode)
    if not dual_stream_enabled():
        return flat

    streams = gen_state.get("streams")
    if not isinstance(streams, dict):
        return flat

    out: List[Dict[str, Any]] = []
    for job in flat:
        j = dict(job)
        jid = str(j.get("id") or "")
        sid = stream_for_job(jid)
        if sid in ("technical", "economic") and is_stream_running({"streams": streams}, sid):
            stream = streams.get(sid)
            if isinstance(stream, dict):
                for sj in stream.get("jobs") or []:
                    if isinstance(sj, dict) and str(sj.get("id") or "") == jid:
                        j = dict(sj)
                        break
        out.append(j)
    return out


def flatten_jobs_from_streams(gen_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Vista plana legacy: merge de jobs por stream con precedencia estable.

    Parte de la cola completa por defecto y sobrescribe con el estado por stream.
    """
    by_id: Dict[str, Dict[str, Any]] = {
        str(j["id"]): dict(j) for j in _default_generation_jobs()
    }
    streams = gen_state.get("streams")
    if isinstance(streams, dict):
        for stream_id in ("technical", "economic", "shared"):
            stream = streams.get(stream_id)
            if not isinstance(stream, dict):
                continue
            for job in stream.get("jobs") or []:
                if not isinstance(job, dict):
                    continue
                jid = str(job.get("id") or "")
                if jid:
                    by_id[jid] = dict(job)

    order = [j["id"] for j in _default_generation_jobs()]
    out: List[Dict[str, Any]] = []
    for jid in order:
        if jid in by_id:
            out.append(by_id[jid])
    for jid, job in by_id.items():
        if jid not in order:
            out.append(job)
    return out


def apply_generation_mode_to_jobs(
    jobs: List[Dict[str, Any]],
    generation_mode: str,
) -> List[Dict[str, Any]]:
    """
    Marca como ``skipped`` los jobs fuera del modo; conserva ``done``/``blocked`` en activos.
    """
    mode = normalize_generation_mode(generation_mode)
    active = active_jobs_for_mode(mode)
    skipped = skipped_jobs_for_mode(mode)
    out: List[Dict[str, Any]] = []
    for job in jobs:
        j = dict(job)
        job_id = str(j.get("id") or "")
        status = str(j.get("status") or "pending")
        if job_id in skipped:
            j["status"] = "skipped"
        elif job_id in active and status == "skipped":
            j["status"] = "pending"
        out.append(j)
    return out


def _merge_stream_jobs_from_existing(
    stream_id: str,
    existing_streams: Dict[str, Any],
    generation_mode: str,
    *,
    resume_generation: bool,
) -> List[Dict[str, Any]]:
    """Construye jobs del stream respetando estado previo en resume."""
    stream_prev = existing_streams.get(stream_id)
    prev_jobs = []
    if isinstance(stream_prev, dict) and isinstance(stream_prev.get("jobs"), list):
        prev_jobs = list(stream_prev["jobs"])

    if resume_generation and prev_jobs:
        base = [dict(j) for j in prev_jobs if isinstance(j, dict)]
    else:
        base = _default_jobs_for_stream(stream_id)

    return apply_generation_mode_to_jobs(base, generation_mode)


def prepare_generation_queue_with_mode(
    session_state: Dict[str, Any],
    *,
    resume_generation: bool,
    orchestrator_mode: str,
    generation_mode: str,
    generation_stream: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Inicializa o reanuda ``generation_state`` aplicando modo y stream (F6).

    Solo aplica a ``generation`` / ``generation_only``.
    """
    if orchestrator_mode not in ("generation_only", "generation"):
        return None

    mode = normalize_generation_mode(generation_mode)
    existing = session_state.get("generation_state")
    existing_dict = existing if isinstance(existing, dict) else {}

    use_streams = dual_stream_enabled() and mode in ("technical", "economic")

    if not use_streams:
        if not resume_generation:
            jobs = apply_generation_mode_to_jobs(_default_generation_jobs(), mode)
            gen_state = {"status": "running", "generation_mode": mode, "jobs": jobs}
            session_state["generation_state"] = gen_state
            return gen_state

        if (
            existing_dict
            and isinstance(existing_dict.get("jobs"), list)
            and len(existing_dict["jobs"]) > 0
            and existing_dict.get("status") != "completed"
        ):
            jobs = apply_generation_mode_to_jobs(list(existing_dict["jobs"]), mode)
            gen_state = {**existing_dict, "generation_mode": mode, "jobs": jobs, "status": "running"}
            session_state["generation_state"] = gen_state
            return gen_state

        jobs = apply_generation_mode_to_jobs(_default_generation_jobs(), mode)
        gen_state = {"status": "running", "generation_mode": mode, "jobs": jobs}
        session_state["generation_state"] = gen_state
        return gen_state

    from app.services.generation_concurrency_controller import resolve_generation_stream_from_input

    stream_id = resolve_generation_stream_from_input(
        {"generation_stream": generation_stream},
        mode,
    )
    if stream_id == "full":
        stream_id = "technical" if mode == "technical" else "economic"

    merged = ensure_streams_structure(existing_dict)
    streams = dict(merged.get("streams") or default_streams_state())

    stream_jobs = _merge_stream_jobs_from_existing(
        stream_id,
        streams,
        mode,
        resume_generation=resume_generation,
    )

    stream_patch: Dict[str, Any] = {
        "status": "running",
        "generation_mode": mode,
        "jobs": stream_jobs,
    }
    if job_id:
        stream_patch["active_job_id"] = str(job_id)

    flat_jobs = _flatten_and_apply_mode_respecting_parallel_streams(
        {
            "streams": {
                **streams,
                stream_id: {**(streams.get(stream_id) or {}), **stream_patch},
            }
        },
        mode,
    )

    gen_state = merge_stream_generation_state(
        merged,
        stream_id,
        stream_patch,
        generation_mode=mode,
        flat_jobs=flat_jobs,
    )
    session_state["generation_state"] = gen_state
    return gen_state


def should_run_generation_job(
    job_id: str,
    generation_mode: str,
    gen_state: Optional[Dict[str, Any]] = None,
) -> bool:
    """True si el job debe ejecutarse en el modo indicado (ignora jobs ya ``skipped``)."""
    mode = normalize_generation_mode(generation_mode)
    if job_id not in active_jobs_for_mode(mode):
        return False
    if gen_state:
        for job in gen_state.get("jobs") or []:
            if job.get("id") == job_id:
                return str(job.get("status") or "pending") != "skipped"
    return True


def gen_job_status(gen_state: Optional[Dict[str, Any]], job_id: str) -> Optional[str]:
    if not gen_state:
        return None
    for job in gen_state.get("jobs") or []:
        if job.get("id") == job_id:
            return str(job.get("status", "pending"))
    if dual_stream_enabled():
        sid = stream_for_job(job_id)
        streams = gen_state.get("streams")
        if isinstance(streams, dict):
            stream = streams.get(sid)
            if isinstance(stream, dict):
                for job in stream.get("jobs") or []:
                    if isinstance(job, dict) and job.get("id") == job_id:
                        return str(job.get("status", "pending"))
    return None


def set_gen_job_status(gen_state: Optional[Dict[str, Any]], job_id: str, status: str) -> None:
    if not gen_state:
        return
    updated = False
    for job in gen_state.get("jobs") or []:
        if job.get("id") == job_id:
            job["status"] = status
            updated = True
            break
    if dual_stream_enabled():
        sid = stream_for_job(job_id)
        streams = gen_state.get("streams")
        if isinstance(streams, dict):
            stream = streams.get(sid)
            if isinstance(stream, dict) and isinstance(stream.get("jobs"), list):
                for job in stream["jobs"]:
                    if isinstance(job, dict) and job.get("id") == job_id:
                        job["status"] = status
                        updated = True
    if updated and dual_stream_enabled() and isinstance(gen_state.get("streams"), dict):
        gen_state["jobs"] = flatten_jobs_from_streams(gen_state)


def mark_skipped_jobs_for_mode(
    gen_state: Optional[Dict[str, Any]],
    generation_mode: str,
) -> None:
    """Re-aplica skips cuando cambia el modo en una sesión activa."""
    if not gen_state or not isinstance(gen_state.get("jobs"), list):
        return
    gen_state["generation_mode"] = normalize_generation_mode(generation_mode)
    gen_state["jobs"] = apply_generation_mode_to_jobs(
        list(gen_state["jobs"]),
        gen_state["generation_mode"],
    )
    if dual_stream_enabled() and isinstance(gen_state.get("streams"), dict):
        for stream_id, stream in gen_state["streams"].items():
            if not isinstance(stream, dict) or not isinstance(stream.get("jobs"), list):
                continue
            stream["jobs"] = apply_generation_mode_to_jobs(
                list(stream["jobs"]),
                gen_state["generation_mode"],
            )
        gen_state["jobs"] = flatten_jobs_from_streams(gen_state)


def sync_flat_jobs_from_streams(gen_state: Optional[Dict[str, Any]]) -> None:
    """Refresca ``jobs`` plano desde streams (tras merge concurrente)."""
    if not gen_state or not dual_stream_enabled():
        return
    if isinstance(gen_state.get("streams"), dict):
        gen_state["jobs"] = flatten_jobs_from_streams(gen_state)
