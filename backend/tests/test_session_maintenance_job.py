"""Tests vínculo sesión ↔ job de mantenimiento (P3-01)."""
from __future__ import annotations

from unittest.mock import patch

from app.services.job_service import (
    clear_session_maintenance_job,
    get_active_session_maintenance_job,
    link_session_maintenance_job,
    update_job_status,
)


def test_maintenance_job_lifecycle():
    sid = "sess_maint_test"
    job_id = "job-maint-99"
    clear_session_maintenance_job(sid)
    update_job_status(job_id, "RUNNING", {"stage": "rehydrate", "pct": 10})
    link_session_maintenance_job(sid, job_id)

    active = get_active_session_maintenance_job(sid)
    assert active.get("job_id") == job_id
    assert active.get("status") == "RUNNING"

    update_job_status(job_id, "COMPLETED", {"pct": 100})
    assert get_active_session_maintenance_job(sid) == {}

    clear_session_maintenance_job(sid)
