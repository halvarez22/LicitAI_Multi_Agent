"""Oracle — expediente_readiness_v1 (CA-INT-1.1)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.services.expediente_readiness_service import (
    _economic_snapshot_hash,
    policy_version,
    resolve_expediente_readiness,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "expediente_readiness"
    / "oracle_cases.json"
)


def _get_path(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _all_blocker_types(payload: dict) -> set[str]:
    types: set[str] = set()
    for section in ("generation", "delivery"):
        blockers = (payload.get(section) or {}).get("blockers") or []
        for b in blockers:
            if isinstance(b, dict) and b.get("error_type"):
                types.add(str(b["error_type"]))
    return types


def _setup_disk(tmp_path: Path, case: dict, session_state: dict) -> str:
    disk = case.get("disk_setup")
    if not isinstance(disk, dict):
        return str(tmp_path)
    root = tmp_path / "outputs" / str(session_state.get("session_id") or "sess")
    root.mkdir(parents=True, exist_ok=True)
    subdirs = disk.get("subdirs") or ["2.propuesta_economica"]
    for sub in subdirs:
        d = root / str(sub)
        d.mkdir(parents=True, exist_ok=True)
        for fname in disk.get("files") or []:
            (d / str(fname)).write_bytes(b"fake")
        fp = disk.get("fingerprint")
        if fp is None and disk.get("fingerprint_from_session"):
            snap = None
            for task in reversed(session_state.get("tasks_completed") or []):
                if isinstance(task, dict) and task.get("task") == "economic_proposal":
                    snap = task.get("result")
                    break
            binding_rfc = (case.get("company_profile") or {}).get("rfc")
            fp = {
                "schema_version": "artifact_fingerprint_v1",
                "scope": "economic",
                "company_id": session_state.get("company_id"),
                "company_rfc": binding_rfc,
                "economic_snapshot_hash": _economic_snapshot_hash(snap if isinstance(snap, dict) else None),
            }
        if isinstance(fp, dict):
            (d / "_LICITAI_FINGERPRINT.json").write_text(
                json.dumps(fp, ensure_ascii=False),
                encoding="utf-8",
            )
    return str(root)


@pytest.fixture(scope="module")
def oracle_cases():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_policy_version_prefix():
    assert policy_version().startswith("expediente-readiness-v1")


@pytest.mark.parametrize(
    "case",
    json.loads(_FIXTURE.read_text(encoding="utf-8")),
    ids=lambda c: c["case_id"],
)
def test_expediente_readiness_oracle(case):
    session_state = dict(case.get("session_state") or {})
    with tempfile.TemporaryDirectory() as tmp:
        output_path = _setup_disk(Path(tmp), case, session_state)
        payload = resolve_expediente_readiness(
            session_state,
            company_profile=case.get("company_profile"),
            company_exists=case.get("company_exists"),
            session_output_path=output_path if case.get("disk_setup") else None,
        )

    assert payload.get("schema_version") == "expediente_readiness_v1"

    expect = case.get("expect") or {}
    for key, expected in expect.items():
        if key == "blocker_types_include":
            types = _all_blocker_types(payload)
            for err in expected:
                assert err in types, f"{case['case_id']}: missing blocker {err}; got {types}"
            continue
        actual = _get_path(payload, key)
        assert actual == expected, f"{case['case_id']}: {key} expected {expected!r}, got {actual!r}"
