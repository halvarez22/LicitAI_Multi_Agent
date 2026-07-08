#!/usr/bin/env python3
"""
Smoke F6 — Concurrencia dual-stream (ADR-001).

Uso:
  cd backend && PYTHONPATH=. python scripts/smoke_dual_stream_concurrency.py
"""

from __future__ import annotations

import sys


def main() -> int:
    errors: list[str] = []

    from app.services.generation_concurrency_controller import (
        job_ids_for_stream,
        policy_version,
        resolve_generation_stream_from_input,
        try_acquire_stream_lock,
    )
    from app.services.generation_queue_controller import prepare_generation_queue_with_mode
    from app.services.generation_wipe_policy import combined_wipe_preserve_subdirs

    if not policy_version().startswith("generation-concurrency-"):
        errors.append("policy_version inválida")

    tech_jobs = job_ids_for_stream("technical")
    eco_jobs = job_ids_for_stream("economic")
    if "technical" not in tech_jobs or "economic_writer" not in eco_jobs:
        errors.append("mapeo job_ids por stream incompleto")

    gen_state: dict = {}
    if not try_acquire_stream_lock(gen_state, "technical", "smoke-tech").acquired:
        errors.append("lock técnico no adquirido")
    if not try_acquire_stream_lock(gen_state, "economic", "smoke-eco").acquired:
        errors.append("lock económico paralelo no adquirido")

    session: dict = {}
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="technical",
        generation_stream="technical",
        job_id="smoke-tech",
    )
    if not state or not state.get("streams"):
        errors.append("cola sin streams F6")

    if resolve_generation_stream_from_input({}, "economic") != "economic":
        errors.append("resolve stream economic falló")

    preserved = combined_wipe_preserve_subdirs("technical", gen_state)
    if not preserved:
        errors.append("wipe no preserva subdirs de stream económico activo")

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1

    print("SMOKE OK: F6 dual-stream concurrency (ADR-001)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
