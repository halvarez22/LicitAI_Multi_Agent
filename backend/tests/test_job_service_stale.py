"""Tests de detección de jobs stale (zombi en Redis)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import job_service


def _iso_ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def mock_redis():
    store: dict[str, str] = {}

    def _get(key):
        return store.get(key)

    def _set(key, value, ex=None):
        store[key] = value

    def _delete(key):
        store.pop(key, None)

    client = MagicMock()
    client.get.side_effect = _get
    client.set.side_effect = _set
    client.delete.side_effect = _delete
    client._store = store
    return client


def test_is_job_stale_when_running_and_idle(mock_redis):
    job = {
        "status": "RUNNING",
        "updated_at": _iso_ago(1300),
        "progress": {"pct": 50},
    }
    with patch.object(job_service, "redis_client", mock_redis):
        with patch.object(job_service.settings, "AGENTS_JOB_STALE_SECONDS", 1200):
            assert job_service.is_job_stale(job) is True


def test_is_not_stale_when_recently_updated(mock_redis):
    job = {
        "status": "RUNNING",
        "updated_at": _iso_ago(300),
    }
    with patch.object(job_service.settings, "AGENTS_JOB_STALE_SECONDS", 1200):
        assert job_service.is_job_stale(job) is False


def test_get_active_session_job_marks_stale_and_clears_link(mock_redis):
    job_id = "dead-job-001"
    session_id = "test_session"
    mock_redis._store[f"session_job:{session_id}"] = job_id
    mock_redis._store[f"job:{job_id}"] = json.dumps(
        {
            "job_id": job_id,
            "status": "RUNNING",
            "created_at": _iso_ago(7200),
            "updated_at": _iso_ago(3600),
            "progress": {"pct": 50, "message": "bloque 15/41"},
        }
    )

    with patch.object(job_service, "redis_client", mock_redis):
        with patch.object(job_service.settings, "AGENTS_JOB_STALE_SECONDS", 1200):
            assert job_service.get_active_session_job(session_id) == {}

    assert f"session_job:{session_id}" not in mock_redis._store
    saved = json.loads(mock_redis._store[f"job:{job_id}"])
    assert saved["status"] == "FAILED"
    assert "Relanza" in saved.get("error", "")
    assert saved.get("forensic_traceback", {}).get("reason") == "stale_job_timeout"


def test_get_active_session_job_returns_running_when_fresh(mock_redis):
    job_id = "live-job-001"
    session_id = "test_session"
    mock_redis._store[f"session_job:{session_id}"] = job_id
    mock_redis._store[f"job:{job_id}"] = json.dumps(
        {
            "job_id": job_id,
            "status": "RUNNING",
            "updated_at": _iso_ago(60),
            "progress": {"pct": 70},
        }
    )

    with patch.object(job_service, "redis_client", mock_redis):
        with patch.object(job_service.settings, "AGENTS_JOB_STALE_SECONDS", 1200):
            active = job_service.get_active_session_job(session_id)

    assert active.get("job_id") == job_id
    assert active.get("status") == "RUNNING"


def test_update_job_status_ignores_running_after_failed(mock_redis):
    job_id = "terminal-job"
    mock_redis._store[f"job:{job_id}"] = json.dumps(
        {
            "job_id": job_id,
            "status": "FAILED",
            "updated_at": _iso_ago(10),
            "error": "stale",
        }
    )
    with patch.object(job_service, "redis_client", mock_redis):
        job_service.update_job_status(
            job_id,
            "RUNNING",
            progress={"pct": 60, "message": "late progress"},
        )
    saved = json.loads(mock_redis._store[f"job:{job_id}"])
    assert saved["status"] == "FAILED"
    assert saved.get("error") == "stale"


def test_get_job_status_repairs_running_with_stale_error(mock_redis):
    job_id = "corrupt-job"
    mock_redis._store[f"job:{job_id}"] = json.dumps(
        {
            "job_id": job_id,
            "status": "RUNNING",
            "updated_at": _iso_ago(100),
            "error": "Análisis interrumpido",
            "forensic_traceback": {"reason": "stale_job_timeout"},
        }
    )
    with patch.object(job_service, "redis_client", mock_redis):
        job = job_service.get_job_status(job_id, reconcile_stale=False)
    assert job["status"] == "FAILED"
