"""Tests HRU del resolver de alcances de descarga (F5.2)."""

from __future__ import annotations

from pathlib import Path

from app.services.artifact_fingerprint_service import build_fingerprint, write_disk_fingerprint
from app.services.delivery_scope_resolver import resolve_scope_artifacts


def _write(p: Path, content: bytes = b"x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)


def _bound_session(**extra: object) -> dict:
    """Sesión mínima con binding válido para gates de readiness."""
    base = {
        "company_id": "co_delivery_test",
        "master_profile": {"rfc": "TESTRFC001", "razon_social": "Empresa Test"},
        "generation_state": {
            "jobs": [
                {"id": "technical", "status": "done"},
                {"id": "formats", "status": "done"},
                {"id": "economic_writer", "status": "done"},
            ]
        },
        "tasks_completed": [
            {"task": "stage_completed:analysis"},
            {
                "task": "economic_proposal",
                "result": {"status": "complete", "total_base": 100.0, "line_items": [{"a": 1}]},
            },
        ],
    }
    base.update(extra)
    return base


def _write_economic_fingerprint(root: Path, session_state: dict) -> None:
    fp = build_fingerprint(session_state, scope="economic")
    write_disk_fingerprint(str(root), "economic", fp)


def test_technical_scope_lists_tech_and_admin_dirs(tmp_path: Path) -> None:
    root = tmp_path / "sess_tech"
    _write(root / "1.propuesta tecnica" / "propuesta.docx", b"tech-body")
    _write(root / "3.documentos administrativos" / "carta.docx", b"admin-body")
    _write(root / "2.propuesta_economica" / "cotizacion.xlsx", b"eco-body")

    out = resolve_scope_artifacts(
        session_id="sess_tech",
        scope="technical",
        session_path=str(root),
        session_state=_bound_session(),
    )

    assert out["ready"] is True
    assert out["artifact_count"] == 2
    paths = {a["relative_path"] for a in out["artifacts"]}
    assert any("1.propuesta tecnica" in p for p in paths)
    assert any("3.documentos administrativos" in p for p in paths)
    assert not any("2.propuesta_economica" in p for p in paths)


def test_economic_scope_excludes_technical(tmp_path: Path) -> None:
    root = tmp_path / "sess_eco"
    _write(root / "1.propuesta tecnica" / "propuesta.docx", b"tech")
    _write(root / "2.propuesta_economica" / "precios.xlsx", b"eco")
    state = _bound_session()
    _write_economic_fingerprint(root, state)

    out = resolve_scope_artifacts(
        session_id="sess_eco",
        scope="economic",
        session_path=str(root),
        session_state=state,
    )

    assert out["artifact_count"] == 1
    assert "2.propuesta_economica" in out["artifacts"][0]["relative_path"]


def test_full_scope_prefers_compranet_validated(tmp_path: Path) -> None:
    root = tmp_path / "sess_full"
    body = b"same-content"
    _write(root / "_compranet_validated" / "SobreTecnica" / "t.docx", body)
    _write(root / "_compranet_validated" / "SobreEconomica" / "e.xlsx", b"eco")
    _write(root / "1.propuesta tecnica" / "dup.docx", body)
    state = _bound_session()
    _write_economic_fingerprint(root, state)

    out = resolve_scope_artifacts(
        session_id="sess_full",
        scope="full",
        session_path=str(root),
        session_state=state,
    )

    assert out["ready"] is True
    assert out["artifact_count"] == 2
    assert all(a["relative_path"].startswith("_compranet_validated/") for a in out["artifacts"])


def test_technical_fallback_compranet_sobres_when_dirs_missing(tmp_path: Path) -> None:
    root = tmp_path / "sess_pack_only"
    _write(root / "_compranet_validated" / "SobreTecnica" / "t.docx", b"tech")
    _write(root / "_compranet_validated" / "SobreEconomica" / "e.xlsx", b"eco")

    out = resolve_scope_artifacts(
        session_id="sess_pack_only",
        scope="technical",
        session_path=str(root),
        session_state=_bound_session(),
    )

    paths = {a["relative_path"] for a in out["artifacts"]}
    assert any("SobreTecnica" in p for p in paths)
    assert not any("SobreEconomica" in p for p in paths)


def test_empty_reason_prices_required_for_economic_pending() -> None:
    state = {
        **_bound_session(),
        "pending_questions": [
            {
                "field": "economic_price_source",
                "type": "economic_validation_blocking",
                "input_mode": "price_source",
            }
        ],
    }
    out = resolve_scope_artifacts(
        session_id="sess_empty",
        scope="economic",
        session_path=None,
        session_state=state,
    )
    assert out["ready"] is False
    assert out["empty_reason"] == "prices_required"
    assert out["empty_reason_message"]


def test_empty_reason_document_quality_gate_for_technical_pending() -> None:
    state = {
        **_bound_session(),
        "pending_questions": [
            {
                "field": "document_quality_gate",
                "type": "document_quality_gate_blocking",
            }
        ],
    }
    out = resolve_scope_artifacts(
        session_id="sess_dqg",
        scope="technical",
        session_path=None,
        session_state=state,
    )
    assert out["ready"] is False
    assert out["empty_reason"] == "document_quality_gate"
    assert out["empty_reason_message"]


def test_artifact_has_human_display_and_download_url(tmp_path: Path) -> None:
    root = tmp_path / "sess_meta"
    _write(root / "1.propuesta tecnica" / "Propuesta.docx", b"content")

    out = resolve_scope_artifacts(
        session_id="sess_meta",
        scope="technical",
        session_path=str(root),
        session_state=_bound_session(),
    )
    art = out["artifacts"][0]
    assert art["display_name"] == "Propuesta técnica"
    assert "1." not in art["display_name"]
    assert art["download_url"].startswith("/api/v1/downloads/file?")
    assert art["provenance_ui"]["job_id"] == "technical"


def test_generation_jobs_done_from_session_state(tmp_path: Path) -> None:
    root = tmp_path / "sess_jobs"
    _write(root / "1.propuesta tecnica" / "t.docx", b"t")
    state = {
        **_bound_session(),
        "generation_state": {
            "generation_mode": "technical",
            "jobs": [
                {"id": "technical", "status": "done"},
                {"id": "formats", "status": "done"},
                {"id": "economic_writer", "status": "skipped"},
            ],
        },
    }
    out = resolve_scope_artifacts(
        session_id="sess_jobs",
        scope="technical",
        session_path=str(root),
        session_state=state,
    )
    assert "technical" in out["generation_jobs"]
    assert "formats" in out["generation_jobs"]
    assert "economic_writer" not in out["generation_jobs"]
