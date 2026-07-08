#!/usr/bin/env python3
"""Smoke F2: modos de generación desacoplados (HRU)."""

from __future__ import annotations

import sys

from app.services.generation_mode_policy import (
    active_jobs_for_mode,
    normalize_generation_mode,
    policy_version,
    skipped_jobs_for_mode,
)
from app.services.generation_queue_controller import prepare_generation_queue_with_mode


def main() -> int:
    assert policy_version(), "missing policy_version"
    for mode in ("full", "technical", "economic"):
        assert normalize_generation_mode(mode) == mode
        active = active_jobs_for_mode(mode)
        skipped = skipped_jobs_for_mode(mode)
        assert not (active & skipped), f"overlap in {mode}"

    session: dict = {}
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="technical",
    )
    assert state and state.get("generation_mode") == "technical"
    skipped_eco = next(j for j in state["jobs"] if j["id"] == "economic_writer")
    assert skipped_eco["status"] == "skipped"

    print("SMOKE OK: decoupled generation F2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
