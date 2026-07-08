"""Tests PR2 — política de wipe selectivo pre-generación."""

from __future__ import annotations

from pathlib import Path

from app.services.generation_wipe_policy import (
    evaluate_pre_generation_wipe,
    force_regenerate_requested,
    output_subdirs_for_writer_job,
)


def test_force_regenerate_requested_honors_policy_key():
    assert force_regenerate_requested({"force_regenerate": True}) is True
    assert force_regenerate_requested({"force_regenerate": False}) is False
    assert force_regenerate_requested(None) is False


def test_evaluate_wipe_force_regenerate_overrides_blocked_artifacts(tmp_path: Path):
    session_dir = tmp_path / "session_out"
    tech_dir = session_dir / "1.propuesta tecnica"
    tech_dir.mkdir(parents=True)
    (tech_dir / "propuesta.docx").write_bytes(b"x")

    gen_state = {
        "jobs": [{"id": "technical", "status": "blocked"}],
    }
    decision = evaluate_pre_generation_wipe(
        generation_mode="technical",
        gen_state=gen_state,
        session_output_path=str(session_dir),
        company_data={"force_regenerate": True},
    )
    assert decision["should_wipe"] is True
    assert decision["reason"] == "force_regenerate"


def test_evaluate_wipe_preserves_when_blocked_job_has_matching_fingerprint(tmp_path: Path):
    session_dir = tmp_path / "session_out"
    tech_dir = session_dir / "1.propuesta tecnica"
    tech_dir.mkdir(parents=True)
    (tech_dir / "anexo.docx").write_bytes(b"doc")

    session_state = {
        "company_id": "co_test",
        "master_profile": {"rfc": "AAA010101AAA"},
        "bases_analysis_fingerprint": "bases123",
    }
    from app.services.artifact_fingerprint_service import build_fingerprint, write_disk_fingerprint

    write_disk_fingerprint(str(session_dir), "technical", build_fingerprint(session_state, scope="technical"))

    gen_state = {
        "jobs": [{"id": "technical", "status": "blocked"}],
    }
    decision = evaluate_pre_generation_wipe(
        generation_mode="technical",
        gen_state=gen_state,
        session_output_path=str(session_dir),
        company_data={},
        session_state=session_state,
    )
    assert decision["should_wipe"] is False
    assert decision["reason"] == "blocked_job_preserves_artifacts"
    assert decision.get("preserved_job_id") == "technical"
    assert decision.get("artifact_count_hint", 0) >= 1


def test_evaluate_wipe_wipes_blocked_without_fingerprint(tmp_path: Path):
    session_dir = tmp_path / "session_out"
    tech_dir = session_dir / "1.propuesta tecnica"
    tech_dir.mkdir(parents=True)
    (tech_dir / "anexo.docx").write_bytes(b"doc")

    gen_state = {
        "jobs": [{"id": "technical", "status": "blocked"}],
    }
    decision = evaluate_pre_generation_wipe(
        generation_mode="technical",
        gen_state=gen_state,
        session_output_path=str(session_dir),
        company_data={},
        session_state={"company_id": "co_test", "master_profile": {"rfc": "AAA010101AAA"}},
    )
    assert decision["should_wipe"] is True
    assert decision["reason"] == "artifact_fingerprint_mismatch"


def test_evaluate_wipe_standard_when_no_blocked_artifacts(tmp_path: Path):
    session_dir = tmp_path / "empty_out"
    session_dir.mkdir()

    gen_state = {
        "jobs": [{"id": "technical", "status": "blocked"}],
    }
    decision = evaluate_pre_generation_wipe(
        generation_mode="technical",
        gen_state=gen_state,
        session_output_path=str(session_dir),
        company_data={},
    )
    assert decision["should_wipe"] is True
    assert decision["reason"] == "standard_pre_generation"


def test_output_subdirs_for_writer_job_technical_excludes_administrative():
    dirs = output_subdirs_for_writer_job("technical")
    assert dirs
    assert not any("administrativ" in d.lower() for d in dirs)


def test_output_subdirs_for_writer_job_formats_administrative_only():
    dirs = output_subdirs_for_writer_job("formats")
    assert dirs
    assert all("administrativ" in d.lower() for d in dirs)
