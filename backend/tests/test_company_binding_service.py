"""Tests HRU R2 — company binding transaccional."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from app.services.company_binding_service import (
    apply_company_binding_patch,
    bind_company_to_session,
    policy_version,
    wipe_output_subdirs,
)
from app.services.expediente_readiness_service import resolve_expediente_readiness


class _FakeMemory:
    def __init__(
        self,
        session: Dict[str, Any],
        companies: Dict[str, Dict[str, Any]],
    ) -> None:
        self._session = dict(session)
        self._companies = companies

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id:
            return dict(self._session)
        return None

    async def save_session(self, session_id: str, data: Dict[str, Any]) -> None:
        self._session = dict(data)

    async def get_company(self, company_id: str) -> Optional[Dict[str, Any]]:
        return self._companies.get(company_id)


def test_policy_version_prefix():
    assert policy_version().startswith("company-binding-v1")


def test_wipe_output_subdirs_only_targets_economic():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "2.propuesta_economica").mkdir()
        (root / "2.propuesta_economica" / "ANEXO.docx").write_bytes(b"x")
        (root / "3.documentos administrativos").mkdir()
        (root / "3.documentos administrativos" / "cedula.docx").write_bytes(b"y")

        n, names = wipe_output_subdirs(str(root), ["2.propuesta_economica"])
        assert n == 1
        assert "2.propuesta_economica" in names
        assert not (root / "2.propuesta_economica").exists()
        assert (root / "3.documentos administrativos" / "cedula.docx").is_file()


def test_apply_binding_company_change_invalidates_snapshot():
    state = {
        "company_id": "co_manavil",
        "master_profile": {"rfc": "SPI060200AG5", "razon_social": "Manavil"},
        "tasks_completed": [
            {"task": "stage_completed:analysis"},
            {"task": "economic_proposal", "result": {"total_base": 13326.63}},
            {"task": "stage_completed:economic", "result": {"status": "success"}},
        ],
        "generation_state": {
            "status": "completed",
            "jobs": [
                {"id": "economic_writer", "status": "done"},
                {"id": "packager", "status": "done"},
            ],
        },
        "artifact_fingerprints_v1": {"economic": {"company_rfc": "SPI060200AG5"}},
    }
    result = apply_company_binding_patch(
        state,
        company_id="co_mayo",
        master_profile={"rfc": "CMT160107S83", "razon_social": "Mayo y Torres"},
        company_changed=True,
    )
    patched = result["session_patch"]
    task_names = {t.get("task") for t in patched.get("tasks_completed") or []}
    assert "economic_proposal" not in task_names
    assert "stage_completed:economic" not in task_names
    assert "artifact_fingerprints_v1" not in patched
    assert patched["company_id"] == "co_mayo"
    assert patched["master_profile"]["rfc"] == "CMT160107S83"
    assert result["tasks_removed"] == 2
    eco_job = next(j for j in patched["generation_state"]["jobs"] if j["id"] == "economic_writer")
    assert eco_job["status"] == "pending"


def test_apply_binding_same_company_refresh_no_wipe_rules():
    state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83", "razon_social": "Mayo y Torres"},
        "tasks_completed": [
            {"task": "economic_proposal", "result": {"status": "complete", "total_base": 100.0}}
        ],
    }
    result = apply_company_binding_patch(
        state,
        company_id="co_mayo",
        master_profile={"rfc": "CMT160107S83", "razon_social": "Mayo y Torres SA"},
        company_changed=False,
    )
    patched = result["session_patch"]
    assert any(t.get("task") == "economic_proposal" for t in patched.get("tasks_completed") or [])
    assert result["tasks_removed"] == 0


@pytest.mark.asyncio
async def test_bind_company_to_session_success():
    memory = _FakeMemory(
        session={
            "company_id": "co_manavil",
            "master_profile": {"rfc": "SPI060200AG5", "razon_social": "Manavil"},
            "tasks_completed": [
                {"task": "stage_completed:analysis"},
                {"task": "economic_proposal", "result": {"status": "complete", "total_base": 1.0}},
            ],
        },
        companies={
            "co_mayo": {
                "id": "co_mayo",
                "name": "Mayo y Torres",
                "master_profile": {"rfc": "CMT160107S83", "razon_social": "Mayo y Torres"},
            }
        },
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        econ = root / "2.propuesta_economica"
        econ.mkdir(parents=True)
        (econ / "OLD.docx").write_bytes(b"manavil")

        result = await bind_company_to_session(
            memory,
            "vigilancia_issste",
            "co_mayo",
            session_output_path=str(root),
        )

    assert result["success"] is True
    assert result["company_changed"] is True
    assert result["invalidation"]["disk_wipe"]["removed_count"] == 1
    assert not (root / "2.propuesta_economica").exists()
    assert result["readiness"]["company_binding"]["binding_valid"] is True
    assert result["readiness"]["company_binding"]["company_rfc"] == "CMT160107S83"


@pytest.mark.asyncio
async def test_bind_company_not_found():
    memory = _FakeMemory(session={"company_id": "co_x"}, companies={})
    with pytest.raises(ValueError, match="COMPANY_NOT_FOUND|no existe"):
        await bind_company_to_session(memory, "sess_x", "co_missing")


@pytest.mark.asyncio
async def test_readiness_after_bind_no_stale_profile():
    memory = _FakeMemory(
        session={
            "company_id": "co_manavil",
            "master_profile": {"rfc": "SPI060200AG5", "razon_social": "Manavil"},
            "tasks_completed": [{"task": "stage_completed:analysis"}],
        },
        companies={
            "co_mayo": {
                "id": "co_mayo",
                "name": "Mayo y Torres",
                "master_profile": {"rfc": "CMT160107S83", "razon_social": "Mayo y Torres"},
            }
        },
    )
    result = await bind_company_to_session(memory, "sess_bind", "co_mayo")
    readiness = result["readiness"]
    assert readiness["company_binding"]["session_profile_stale"] is False
    assert readiness["company_binding"]["orphan_company_id"] is False


def test_orphan_session_detected_by_readiness_without_bind():
    state = {
        "session_id": "sess_orphan",
        "company_id": "co_deleted",
        "master_profile": {"rfc": "SPI060200AG5", "razon_social": "Manavil"},
    }
    readiness = resolve_expediente_readiness(state, company_exists=False)
    assert readiness["company_binding"]["orphan_company_id"] is True
    assert readiness["company_binding"]["binding_valid"] is False
