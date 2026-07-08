"""Tests HRU: política versionada de defer económico (H/R/U)."""

from __future__ import annotations

from pathlib import Path

from docx import Document

from app.config.settings import settings as app_settings
from app.services.chat_fill_quality_queue_policy import fill_quality_needs_chat_capture
from app.services.chat_gate5_formatter import build_compact_session_resume, count_visible_lines
from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.document_fill_deferral_policy import (
    load_document_fill_deferral_policy,
    policy_version,
)
from app.services.document_fill_quality_gate import validate_generated_documents_fill


def _make_docx(path: Path, lines: list[str]) -> None:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)


def test_deferral_policy_json_versioned():
    policy = load_document_fill_deferral_policy()
    assert policy.get("policy_version")
    assert "admin_economic_deferral" in policy
    assert policy_version().startswith("document-fill-deferral-")


def test_deferral_obra_apu_y_servicios_tarifa(tmp_path, monkeypatch):
    """Universalidad: obra (APU) y servicios (tarifa) no bloquean formats."""
    monkeypatch.setattr(app_settings, "DOCUMENT_FILL_QUALITY_GATE_MODE", "enforce")
    monkeypatch.setattr(app_settings, "ADMIN_ECONOMIC_DEFERRAL", True)
    profile = {
        "razon_social": "Empresa Demo SA",
        "rfc": "EDM010101AAA",
        "representante_legal": "Ana Demo",
    }

    obra = tmp_path / "analisis_precios_unitarios.docx"
    _make_docx(obra, ["...", "Partida 1"])
    out_obra = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(obra)}],
        master_profile=profile,
    )

    servicios = tmp_path / "anexo_calculo_costos.docx"
    _make_docx(servicios, ["Tarifa mensual para horario: _______________"])
    out_servicios = validate_generated_documents_fill(
        stage="formats",
        generated_documents=[{"ruta": str(servicios)}],
        master_profile=profile,
    )

    assert out_obra["validation_passed"] is True
    assert out_servicios["validation_passed"] is True
    assert out_obra["deferral_policy_version"] == policy_version()
    assert out_servicios["deferral_policy_version"] == policy_version()


def test_deferred_warnings_no_chat_capture():
    """Regresión: warnings diferidos no activan captura HITL en chat."""
    issues = [
        {
            "document_id": "calculo_costos.xlsx",
            "field_key": "tarifa_mensual",
            "error_type": "required_field_missing",
            "expected_rule": "deferred_to_economic_stage",
            "severity": "warn",
        }
    ]
    state = {"triage_context": {"tender_category": "SERVICIOS"}}
    assert fill_quality_needs_chat_capture(issues, state) is False


def test_session_resume_usa_empresa_ui_gate5():
    """Bootstrap/resume compacto con empresa UI (sin hardcode por licitación)."""
    state = {
        "name": "Licitación demo",
        "master_profile": {"razon_social": "Empresa Stale SA"},
        "tasks_completed": [{"task": "stage_completed:analysis", "result": {}}],
        "pending_questions": [],
        "last_orchestrator_decision": {"stop_reason": "IDLE"},
    }
    msg = build_compact_session_resume(
        state,
        company_label_override="Empresa Seleccionada UI SA",
    )
    assert count_visible_lines(msg) <= 3
    assert_user_visible_clean(msg)
    assert "Empresa Seleccionada UI SA" in msg
    assert "Empresa Stale" not in msg
