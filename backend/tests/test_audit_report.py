"""Pruebas del generador de reporte de auditoría de sesión (legal/ops)."""
from __future__ import annotations

import csv
import importlib.util
import json
import time
from pathlib import Path

import pytest


def _load_generate_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_audit_report.py"
    spec = importlib.util.spec_from_file_location("generate_audit_report", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_session_fixture(name: str) -> dict:
    p = Path(__file__).parent / "fixtures" / "real_sessions" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _session_to_exports(session: dict, session_id: str) -> dict[str, dict]:
    """Convierte fixture de sesión (shape gate) a payloads tipo stage export."""

    def wrap(part: dict, agent_id: str) -> dict:
        inner = part.get("data") if isinstance(part.get("data"), dict) else part
        return {
            "status": "success",
            "agent_id": agent_id,
            "session_id": session_id,
            "data": inner,
        }

    return {
        "analysis.json": wrap(session["analysis"], "analyst_001"),
        "compliance.json": wrap(session["compliance"], "compliance_001"),
        "economic.json": wrap(session["economic"], "economic_001"),
    }


def _write_min_backend(tmp: Path, session_id: str, exports: dict[str, dict], latest_job: dict, oracle: dict | None) -> Path:
    root = tmp / "backend"
    (root / "out" / "oracle_real").mkdir(parents=True)
    for fname, payload in exports.items():
        (root / "out" / "oracle_real" / fname).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (root / "out" / "metadata").mkdir(parents=True, exist_ok=True)
    (root / "out" / "metadata" / "latest_job.json").write_text(
        json.dumps(latest_job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if oracle is not None:
        (root / "out" / "oracle_report.json").write_text(
            json.dumps(oracle, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return root


@pytest.mark.regression
def test_audit_report_blocking_session_la_51_style_fixture(tmp_path: Path) -> None:
    """Sesión anónima con 12.1.R bloqueante (misma forma que vigilancia / gate real)."""
    mod = _load_generate_module()
    session = _load_session_fixture("example_compliance_blocking_r")
    session_id = "audit_session_blocking_r_v1"
    exports = _session_to_exports(session, session_id)
    latest_job = {
        "session_id": session_id,
        "status": "hard_disqualification",
        "metadata": {
            "telemetry": {
                "stages": {
                    "analysis": {"duration_seconds": 12.0},
                    "compliance": {"duration_seconds": 200.5},
                }
            }
        },
        "orchestrator_decision": {"stop_reason": "COMPLIANCE_GATE_BLOCKING"},
    }
    oracle = {
        "timestamp": "2026-04-09T00:00:00+00:00",
        "total_issues": 0,
        "reported_issues": 0,
        "blocking_issues": 0,
        "issues": [],
    }
    root = _write_min_backend(tmp_path, session_id, exports, latest_job, oracle)
    out_dir = root / "out" / "audit" / session_id
    t0 = time.perf_counter()
    code, report = mod.build_audit_report(root, session_id, out_dir)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0
    assert code == 0
    assert report["pipeline_status"] == "HARD_DISQUALIFICATION"
    assert report["compliance_gate"]["is_blocking"] is True
    assert "12.1.R" in report["compliance_gate"]["failed_rules"]
    assert report["telemetry"]["analysis_duration_s"] == 12.0
    assert report["telemetry"]["compliance_duration_s"] == 200.5
    assert report["telemetry"]["economic_duration_s"] is None
    assert report["oracle_validation"]["status"] == "OK"
    assert report["packaging"] == "skipped"

    data = json.loads((out_dir / "audit_report.json").read_text(encoding="utf-8"))
    assert data["session_id"] == session_id
    assert len(data["compliance_gate"]["evidence_summary"]) >= 1

    with (out_dir / "audit_summary.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["case_id", "estado", "criticidad", "evidencia_snippet", "recomendacion"]
    assert any(r and r[0] == "12.1.R" for r in rows[1:])


def test_audit_report_ok_session_and_missing_oracle(tmp_path: Path) -> None:
    mod = _load_generate_module()
    session = _load_session_fixture("example_compliance_ok")
    session_id = "audit_session_ok_v1"
    exports = _session_to_exports(session, session_id)
    latest_job = {
        "session_id": session_id,
        "status": "success",
        "metadata": {
            "telemetry": {
                "stages": {
                    "analysis": {"duration_seconds": 1.0},
                    "compliance": {"duration_seconds": 2.0},
                    "economic": {"duration_seconds": 3.0},
                }
            }
        },
        "orchestrator_decision": {},
    }
    root = _write_min_backend(tmp_path, session_id, exports, latest_job, None)
    out_dir = root / "out" / "audit" / session_id
    code, report = mod.build_audit_report(root, session_id, out_dir)
    assert code == 0
    assert report["compliance_gate"]["is_blocking"] is False
    assert report["oracle_validation"]["status"] == "MISSING"
    assert "oracle_report.json no encontrado" in (report["oracle_validation"].get("note") or "")
