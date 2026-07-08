"""Tests CONTAM01 — integridad de descarga vs fingerprint (HRU R4)."""

from __future__ import annotations

from pathlib import Path

from app.services.artifact_fingerprint_service import write_disk_fingerprint
from app.services.delivery_scope_resolver import resolve_scope_artifacts


def _write(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


def test_contam01_economic_files_hidden_when_fingerprint_mismatch(tmp_path: Path) -> None:
    """
    CONTAM01: archivos Manavil en disco + sesión Mayo → lista vacía y razón estable.

    Replica el desastre vigilancia_issste: cotización visible en disco pero empresa ligada distinta.
    """
    root = tmp_path / "vigilancia_issste"
    _write(root / "2.propuesta_economica" / "ANEXO_ECONOMICO.docx", b"manavil-body")
    write_disk_fingerprint(
        str(root),
        "economic",
        {
            "company_rfc": "SPI060200AG5",
            "economic_snapshot_hash": "deadbeef",
        },
    )

    session_state = {
        "session_id": "vigilancia_issste",
        "company_id": "co_1780079004578",
        "master_profile": {
            "rfc": "CMT160107S83",
            "razon_social": "Mayo y Torres",
        },
        "tasks_completed": [
            {"task": "stage_completed:analysis"},
            {
                "task": "economic_proposal",
                "result": {
                    "status": "complete",
                    "total_base": 5800.0,
                    "line_items": [{"concepto": "vigilancia", "importe": 5800.0}],
                },
            },
        ],
        "generation_state": {
            "jobs": [
                {"id": "technical", "status": "done"},
                {"id": "formats", "status": "done"},
                {"id": "economic_writer", "status": "blocked"},
            ]
        },
    }
    company_profile = {
        "rfc": "CMT160107S83",
        "razon_social": "Mayo y Torres",
    }

    out = resolve_scope_artifacts(
        session_id="vigilancia_issste",
        scope="economic",
        session_path=str(root),
        session_state=session_state,
        company_profile=company_profile,
        company_exists=True,
    )

    assert out["artifact_count"] == 0
    assert out["ready"] is False
    assert out["readiness_integrity_blocked"] is True
    assert out["empty_reason"] == "artifact_fingerprint_mismatch"
    assert out["empty_reason_message"]


def test_economic_delivery_allowed_when_fingerprint_matches(tmp_path: Path) -> None:
    """Control positivo: mismo RFC en sesión y sidecar → entrega permitida."""
    from app.services.artifact_fingerprint_service import build_fingerprint

    root = tmp_path / "sess_ok"
    _write(root / "2.propuesta_economica" / "cotizacion.xlsx", b"eco")
    session_state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83"},
        "tasks_completed": [
            {
                "task": "economic_proposal",
                "result": {"status": "complete", "total_base": 100.0, "line_items": [{"a": 1}]},
            }
        ],
        "generation_state": {
            "jobs": [{"id": "economic_writer", "status": "done"}]
        },
    }
    write_disk_fingerprint(str(root), "economic", build_fingerprint(session_state, scope="economic"))

    out = resolve_scope_artifacts(
        session_id="sess_ok",
        scope="economic",
        session_path=str(root),
        session_state=session_state,
        company_profile={"rfc": "CMT160107S83"},
        company_exists=True,
    )

    assert out["artifact_count"] == 1
    assert out["ready"] is True
    assert out["readiness_integrity_blocked"] is False
