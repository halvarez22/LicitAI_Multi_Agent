"""Tests F6: concurrencia dual-stream (ADR-001)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.generation_concurrency_controller import (
    StreamLockResult,
    active_stream_ids,
    is_stream_running,
    preserve_subdirs_for_active_streams,
    release_stream_lock,
    resolve_generation_stream_from_input,
    try_acquire_stream_lock,
)
from app.services.generation_queue_controller import (
    flatten_jobs_from_streams,
    gen_job_status,
    prepare_generation_queue_with_mode,
    set_gen_job_status,
)
from app.services.generation_wipe_policy import combined_wipe_preserve_subdirs


@pytest.fixture(autouse=True)
def enable_dual_stream(monkeypatch):
    monkeypatch.setattr(
        "app.services.generation_concurrency_controller.dual_stream_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.generation_queue_controller.dual_stream_enabled",
        lambda: True,
    )


def test_resolve_generation_stream_from_mode():
    assert resolve_generation_stream_from_input({}, "technical") == "technical"
    assert resolve_generation_stream_from_input({}, "economic") == "economic"
    assert (
        resolve_generation_stream_from_input(
            {"generation_stream": "economic"},
            "technical",
        )
        == "economic"
    )


def test_parallel_stream_locks_technical_and_economic():
    gen_state: dict = {}
    tech = try_acquire_stream_lock(gen_state, "technical", "job-tech-1")
    eco = try_acquire_stream_lock(gen_state, "economic", "job-eco-1")
    assert tech.acquired is True
    assert eco.acquired is True
    assert is_stream_running(gen_state, "technical")
    assert is_stream_running(gen_state, "economic")
    assert active_stream_ids(gen_state) == ["technical", "economic"]


def test_same_stream_second_job_blocked():
    gen_state: dict = {}
    first = try_acquire_stream_lock(gen_state, "technical", "job-a")
    second = try_acquire_stream_lock(gen_state, "technical", "job-b")
    assert first.acquired is True
    assert second.acquired is False
    assert second.reason == "stream_already_running"
    assert second.holder_job_id == "job-a"


def test_release_stream_lock_only_holder():
    gen_state: dict = {}
    try_acquire_stream_lock(gen_state, "economic", "job-eco")
    release_stream_lock(gen_state, "economic", "job-other")
    assert is_stream_running(gen_state, "economic")
    release_stream_lock(gen_state, "economic", "job-eco")
    assert not is_stream_running(gen_state, "economic")


def test_prepare_queue_technical_preserves_economic_stream_on_resume():
    session = {
        "generation_state": {
            "streams": {
                "technical": {"status": "idle", "jobs": [], "lock": None},
                "economic": {
                    "status": "running",
                    "generation_mode": "economic",
                    "jobs": [{"id": "economic_writer", "status": "running"}],
                    "lock": {"holder_job_id": "job-eco-parallel"},
                },
                "shared": {"status": "idle", "jobs": [], "lock": None},
            },
            "jobs": [{"id": "economic_writer", "status": "running"}],
        }
    }
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=True,
        orchestrator_mode="generation_only",
        generation_mode="technical",
        generation_stream="technical",
        job_id="job-tech-parallel",
    )
    assert state is not None
    eco_jobs = state["streams"]["economic"]["jobs"]
    assert gen_job_status(state, "economic_writer") == "running"
    assert gen_job_status(state, "technical") in ("pending", "running", "done", "blocked")
    assert eco_jobs


def test_flatten_jobs_from_streams_order():
    gen_state = {
        "streams": {
            "technical": {
                "jobs": [
                    {"id": "datagap", "status": "done"},
                    {"id": "technical", "status": "running"},
                ]
            },
            "economic": {
                "jobs": [{"id": "economic_writer", "status": "pending"}]
            },
            "shared": {
                "jobs": [{"id": "packager", "status": "pending"}]
            },
        }
    }
    flat = flatten_jobs_from_streams(gen_state)
    ids = [j["id"] for j in flat]
    assert ids.index("datagap") < ids.index("technical")
    assert ids.index("economic_writer") < ids.index("packager")


def test_set_gen_job_status_updates_stream_and_flat():
    gen_state = {
        "streams": {
            "technical": {
                "jobs": [{"id": "technical", "status": "pending"}],
            },
            "economic": {"jobs": []},
            "shared": {"jobs": []},
        },
        "jobs": [{"id": "technical", "status": "pending"}],
    }
    set_gen_job_status(gen_state, "technical", "done")
    assert gen_job_status(gen_state, "technical") == "done"
    assert gen_state["streams"]["technical"]["jobs"][0]["status"] == "done"


def test_combined_wipe_preserves_sibling_stream_dirs():
    gen_state: dict = {}
    try_acquire_stream_lock(gen_state, "economic", "job-eco")
    preserved = combined_wipe_preserve_subdirs("technical", gen_state)
    assert preserved
    assert preserve_subdirs_for_active_streams(gen_state)


def test_dual_stream_off_uses_legacy_queue(monkeypatch):
    monkeypatch.setattr(
        "app.services.generation_queue_controller.dual_stream_enabled",
        lambda: False,
    )
    session: dict = {}
    state = prepare_generation_queue_with_mode(
        session,
        resume_generation=False,
        orchestrator_mode="generation_only",
        generation_mode="technical",
    )
    assert state is not None
    assert "streams" not in state or not state.get("streams")
    assert gen_job_status(state, "economic_writer") == "skipped"
