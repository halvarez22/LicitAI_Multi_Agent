"""Tests HRU panel formatos y bootstrap chat obra."""

from __future__ import annotations

from app.services.chat_gate5_formatter import (
    build_compact_session_resume,
    build_obra_documentary_bootstrap,
    count_visible_lines,
)
from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.formats_panel_hru_service import (
    is_panel_label_ocr_corrupted,
    normalize_formats_panel_payload,
    normalize_formats_panel_row,
    resolve_panel_display_name,
    resolve_panel_sobre_bucket,
)


def test_ocr_corruption_detected():
    assert is_panel_label_ocr_corrupted("Anexo E-2 PRESUPUESTO 52 52 52 52")
    assert is_panel_label_ocr_corrupted("Anexo T-2: 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18")
    assert not is_panel_label_ocr_corrupted("Anexo T-B-2 Documentación de experiencia")


def test_resolve_display_name_t2_universal():
    raw = "Anexo T-2: 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21"
    name = resolve_panel_display_name(raw)
    assert "T-2" in name
    assert "contratos" in name.lower()
    assert "3 4 5" not in name


def test_resolve_display_name_e2_universal():
    raw = "Anexo E-2 PRESUPUESTO_52_52_52_52.docx"
    name = resolve_panel_display_name(raw)
    assert "E-2" in name
    assert "PRESUPUESTO_52" not in name


def test_e2_bucket_economico_not_tecnico():
    assert resolve_panel_sobre_bucket("Anexo E-2 PRESUPUESTO 52 52") == "sobre_2_economico"
    assert resolve_panel_sobre_bucket("Anexo E-4 PROGRAMAS DE OBRA") == "sobre_2_economico"
    assert resolve_panel_sobre_bucket("Anexo T-B-2 experiencia técnica") == "sobre_1_tecnico"


def test_normalize_panel_rebuckets_e2():
    panel = {
        "sobre_1_tecnico": [
            {
                "nombre_canonico": "Anexo E-2 PRESUPUESTO 52 52 52",
                "tipo": "generar",
                "tipo_accion_final": "generar",
            },
            {
                "nombre_canonico": "Anexo T-2: 3 4 5 6 7 8 9 10 11 12",
                "tipo": "generar",
                "tipo_accion_final": "generar",
            },
        ],
        "sobre_2_economico": [],
        "requisitos_legales": [],
        "otros_requisitos_criticos": [],
        "_meta": {},
    }
    out = normalize_formats_panel_payload(panel)
    eco = out.get("sobre_2_economico") or []
    tech = out.get("sobre_1_tecnico") or []
    assert any("E-2" in str(x.get("nombre_canonico")) for x in eco)
    assert any("T-2" in str(x.get("nombre_canonico")) for x in tech)
    assert not any("PRESUPUESTO_52" in str(x.get("nombre_canonico")) for x in eco + tech)


def test_obra_bootstrap_message_hru():
    state = {
        "name": "BARDA PRIMARIA LOPEZ RAYON",
        "triage_context": {"tender_category": "OBRA", "law": "LOPSRM"},
        "master_profile": {"razon_social": "Constructora Demo"},
        "compliance_master_list": {
            "formatos": [{"nombre": "Anexo T-2 contratos vigentes"}],
            "tecnico": [
                {"nombre": "Anexo T-B-2 Documentación de experiencia", "tipo_accion_final": "presentar_fisico"},
            ],
        },
        "document_candidates_consolidated": {
            "sobre_1_tecnico": [
                {"nombre_canonico": "Anexo T-3 Modelo contrato", "tipo_accion_final": "generar"},
            ],
        },
        "last_orchestrator_decision": {"stop_reason": "INCOMPLETE_FORMATS_DATA"},
        "tasks_completed": [{"task": "stage_completed:analysis", "result": {}}],
        "pending_questions": [],
    }
    msg = build_compact_session_resume(state)
    assert count_visible_lines(msg) <= 3
    assert_user_visible_clean(msg)
    assert "Documentos detectados" in msg
    assert "[Consignar]" in msg
    assert "INCOMPLETE" not in msg
    assert "generar propuesta económica" not in msg.lower()


def test_obra_bootstrap_direct():
    msg = build_obra_documentary_bootstrap(
        {
            "name": "Obra demo",
            "document_candidates_consolidated": {
                "sobre_1_tecnico": [
                    {"nombre_canonico": "Anexo T-2 contratos", "tipo_accion_final": "presentar_fisico"},
                ],
            },
        }
    )
    assert "Formatos/Anexos Detectados" in msg
    assert "Documentos detectados" in msg
