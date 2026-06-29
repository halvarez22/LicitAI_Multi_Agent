"""Tests bootstrap HRU universal de plan de expediente (cualquier licitación)."""

from __future__ import annotations

from app.services.chat_expediente_bootstrap_service import (
    build_expediente_plan_bootstrap,
    collect_expediente_bootstrap_facts,
)
from app.services.chat_gate5_formatter import build_compact_session_resume, count_visible_lines
from app.services.chat_stop_reason_map import assert_user_visible_clean


def _barda_state() -> dict:
    return {
        "name": "BARDA PRIMARIA LOPEZ RAYON",
        "triage_context": {"tender_category": "OBRA", "law": "LOPSRM"},
        "master_profile": {"razon_social": "Constructora Nacional S.A."},
        "compliance_master_list": {
            "formatos": [
                {"nombre": "Anexo T-2 contratos vigentes de obra"},
                {"nombre": "Documentación que compruebe su experiencia y capacidad técnica"},
            ],
            "tecnico": [
                {
                    "nombre": "Anexo T-B-2 Documentación de experiencia",
                    "tipo_accion_final": "presentar_fisico",
                },
            ],
        },
        "document_candidates_consolidated": {
            "sobre_1_tecnico": [
                {
                    "nombre_canonico": "Anexo T-3 Modelo de contrato firmado",
                    "tipo_accion_final": "generar",
                },
                {
                    "nombre_canonico": "Anexo T-6 Manifestación bajo protesta",
                    "tipo_accion_final": "generar",
                },
            ],
            "sobre_2_economico": [
                {"nombre_canonico": "Anexo E-2 Presupuesto", "tipo_accion_final": "generar"},
            ],
        },
        "last_orchestrator_decision": {"stop_reason": "INCOMPLETE_FORMATS_DATA"},
        "tasks_completed": [{"task": "stage_completed:analysis", "result": {}}],
        "pending_questions": [],
    }


def _servicios_state() -> dict:
    return {
        "name": "Limpieza ISSSTE 2024",
        "triage_context": {"tender_category": "SERVICIOS"},
        "master_profile": {"razon_social": "Servicios Integrales SA"},
        "compliance_master_list": {
            "administrativo": [
                {
                    "nombre": "Opinión de cumplimiento SAT",
                    "tipo_accion_final": "presentar_fisico",
                },
            ],
        },
        "document_candidates_consolidated": {
            "sobre_1_tecnico": [
                {"nombre_canonico": "Propuesta técnica TE-01", "tipo_accion_final": "generar"},
            ],
        },
        "tasks_completed": [{"task": "stage_completed:analysis", "result": {}}],
        "pending_questions": [],
        "last_orchestrator_decision": {"stop_reason": "IDLE"},
    }


def test_collect_facts_obra_user_vs_generate():
    facts = collect_expediente_bootstrap_facts(_barda_state())
    assert facts.user_attach_count >= 1
    assert facts.generate_count >= 2
    assert "Constructora" in facts.company_label


def test_collect_facts_servicios():
    facts = collect_expediente_bootstrap_facts(_servicios_state())
    assert facts.user_attach_count >= 1
    assert facts.generate_count >= 1


def test_bootstrap_gate5_obra():
    msg = build_expediente_plan_bootstrap(_barda_state())
    assert count_visible_lines(msg) <= 3
    assert_user_visible_clean(msg)
    assert "Documentos detectados" in msg
    assert "Formatos/Anexos Detectados" in msg
    assert "[Consignar]" in msg
    assert "Constructora" in msg
    assert "INCOMPLETE" not in msg


def test_bootstrap_gate5_servicios():
    msg = build_expediente_plan_bootstrap(_servicios_state())
    assert count_visible_lines(msg) <= 3
    assert "Documentos detectados" in msg
    assert "Servicios Integrales" in msg
    assert "T-2" not in msg


def test_compact_session_resume_uses_universal_bootstrap():
    msg = build_compact_session_resume(_barda_state())
    assert count_visible_lines(msg) <= 3
    assert "Plan de expediente listo" in msg
    assert "generar propuesta económica" not in msg.lower()
