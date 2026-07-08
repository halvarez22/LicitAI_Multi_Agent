"""Tests HRU R3 — artifact fingerprint e integridad de wipe."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.services.artifact_fingerprint_service import (
    build_fingerprint,
    disk_fingerprint_matches_session,
    fingerprint_matches,
    materialize_economic_fingerprint,
    policy_version,
    scopes_with_fingerprint_mismatch,
    write_disk_fingerprint,
)
from app.services.generation_wipe_policy import evaluate_pre_generation_wipe


class _FakeMemory:
    def __init__(self, session: dict) -> None:
        self._session = dict(session)
        self.saved: dict | None = None

    async def save_session(self, session_id: str, data: dict) -> None:
        self.saved = dict(data)
        self._session.update(data)


def test_policy_version_prefix():
    assert policy_version().startswith("artifact-integrity-v1")


def test_fingerprint_matches_rfc():
    expected = {"company_rfc": "CMT160107S83", "economic_snapshot_hash": "abc123"}
    assert fingerprint_matches(expected, {"company_rfc": "CMT160107S83", "economic_snapshot_hash": "abc123"})
    assert not fingerprint_matches(expected, {"company_rfc": "SPI060200AG5"})


def test_scopes_with_mismatch_when_old_rfc_on_disk():
    state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83"},
        "tasks_completed": [
            {"task": "economic_proposal", "result": {"status": "complete", "total_base": 100.0}}
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        econ = root / "2.propuesta_economica"
        econ.mkdir()
        (econ / "ANEXO.docx").write_bytes(b"x")
        write_disk_fingerprint(
            str(root),
            "economic",
            {
                "company_rfc": "SPI060200AG5",
                "economic_snapshot_hash": "deadbeef",
            },
        )
        mismatched = scopes_with_fingerprint_mismatch(str(root), state, scopes=["economic"])
    assert mismatched == ["economic"]


def test_disk_matches_after_write():
    state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83"},
        "tasks_completed": [
            {"task": "economic_proposal", "result": {"status": "complete", "total_base": 100.0, "line_items": [{"a": 1}]}}
        ],
    }
    fp = build_fingerprint(state, scope="economic")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        econ = root / "2.propuesta_economica"
        econ.mkdir()
        (econ / "ANEXO.docx").write_bytes(b"x")
        write_disk_fingerprint(str(root), "economic", fp)
        assert disk_fingerprint_matches_session(str(root), state, scope="economic")


@pytest.mark.asyncio
async def test_materialize_economic_fingerprint_persists_session():
    state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83"},
        "tasks_completed": [
            {"task": "economic_proposal", "result": {"status": "complete", "total_base": 50.0}}
        ],
    }
    memory = _FakeMemory(state)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "2.propuesta_economica"
        root.mkdir(parents=True)
        result = await materialize_economic_fingerprint(
            memory,
            "sess_fp",
            state,
            session_output_path=str(root.parent),
            generation_job_id="job-1",
        )
    assert result["fingerprint"]["company_rfc"] == "CMT160107S83"
    assert memory.saved is not None
    assert "artifact_fingerprints_v1" in memory.saved


def test_wipe_mismatch_overrides_blocked_preserve(tmp_path: Path):
    session_dir = tmp_path / "session_out"
    econ_dir = session_dir / "2.propuesta_economica"
    econ_dir.mkdir(parents=True)
    (econ_dir / "anexo.docx").write_bytes(b"doc")
    (econ_dir / "_LICITAI_FINGERPRINT.json").write_text(
        json.dumps({"company_rfc": "SPI060200AG5", "economic_snapshot_hash": "old"}),
        encoding="utf-8",
    )
    session_state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83"},
        "tasks_completed": [
            {"task": "economic_proposal", "result": {"status": "complete", "total_base": 1.0}}
        ],
    }
    gen_state = {"jobs": [{"id": "economic_writer", "status": "blocked"}]}
    decision = evaluate_pre_generation_wipe(
        generation_mode="economic",
        gen_state=gen_state,
        session_output_path=str(session_dir),
        company_data={},
        session_state=session_state,
    )
    assert decision["should_wipe"] is True
    assert decision["reason"] == "artifact_fingerprint_mismatch"


def test_wipe_preserves_blocked_when_fingerprint_matches(tmp_path: Path):
    session_dir = tmp_path / "session_out"
    tech_dir = session_dir / "1.propuesta tecnica"
    tech_dir.mkdir(parents=True)
    (tech_dir / "anexo.docx").write_bytes(b"doc")
    session_state = {
        "company_id": "co_test",
        "master_profile": {"rfc": "AAA010101AAA"},
        "bases_analysis_fingerprint": "bases123",
    }
    fp = build_fingerprint(session_state, scope="technical")
    write_disk_fingerprint(str(session_dir), "technical", fp)
    gen_state = {"jobs": [{"id": "technical", "status": "blocked"}]}
    decision = evaluate_pre_generation_wipe(
        generation_mode="technical",
        gen_state=gen_state,
        session_output_path=str(session_dir),
        company_data={},
        session_state=session_state,
    )
    assert decision["should_wipe"] is False
    assert decision["reason"] == "blocked_job_preserves_artifacts"
