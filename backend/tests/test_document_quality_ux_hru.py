"""Tests HRU UX de calidad documental y misión del expediente."""

from __future__ import annotations

from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.document_quality_ux import (
    build_document_quality_gate_message,
    build_document_quality_pending_question,
    normalize_document_quality_pending_item,
    normalize_expediente_pending_questions,
    policy_version,
)
from app.services.expediente_mission_router import resolve_expediente_mission


def test_policy_version():
    assert policy_version().startswith("document-quality-ux-")


def test_gate_message_no_forensic_jargon():
    msg = build_document_quality_gate_message(
        gate={"reason": "no_actionable_generate_items", "metrics": {"total_items": 5}},
        session_state={"name": "Vigilancia zona norte"},
    )
    assert "presentar_fisico" not in msg
    assert "evidence_match" not in msg
    assert "Vigilancia" in msg
    assert_user_visible_clean(msg)


def test_normalize_legacy_pending_question():
    legacy = {
        "field": "document_quality_gate",
        "label": "Confirmar clasificación documental",
        "question": (
            "La lista documental técnica tiene baja calidad estructural. "
            "Debes reclasificar requisitos (generar/presentar_fisico/informativo)."
        ),
        "type": "document_quality_gate_blocking",
    }
    out = normalize_document_quality_pending_item(
        legacy,
        session_state={
            "name": "Servicios generales",
            "last_document_quality_waiting_hints": {
                "reason": "unknown_ratio_above_threshold",
                "metrics": {"unknown_count": 3, "total_items": 5},
            },
        },
    )
    assert out["type"] == "quality_validation_blocking"
    assert "presentar_fisico" not in str(out.get("question") or "")
    assert_user_visible_clean(str(out.get("question") or ""))


def test_mission_router_prioritizes_economic_over_quality():
    state = {
        "name": "Vigilancia HRU",
        "session_line_items": [
            {
                "concepto_raw": "Zona A",
                "extra": {"location_label": "Zona A"},
            }
        ],
        "economic_user_inputs": {},
        "pending_questions": [
            normalize_document_quality_pending_item(
                {
                    "type": "document_quality_gate_blocking",
                    "field": "document_quality_gate",
                    "question": "legacy",
                },
                {"name": "Vigilancia HRU"},
            )
        ],
        "last_document_quality_waiting_hints": {"reason": "no_actionable_generate_items", "metrics": {}},
    }
    mission = resolve_expediente_mission(state)
    assert mission is not None
    assert mission.mission_id in ("economic_capture", "service_dual_opening")
    assert "cotiz" in mission.message.lower() or "precio" in mission.message.lower()


def test_mission_router_vigilancia_without_line_items():
    state = {
        "name": "VIGILANCIA ISSSTE",
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "technical_post_analysis_hook_pending": True,
        "economic_user_inputs": {"allow_zero_total_base_ack": True},
        "compliance_master_list": {
            "tecnico": [
                {
                    "nombre": "Propuesta Técnica describiendo especificaciones",
                    "tipo_accion": "generar",
                }
            ],
            "formatos": [],
        },
    }
    mission = resolve_expediente_mission(state)
    assert mission is not None
    assert mission.mission_id == "service_dual_opening"
    assert "Cotización pendiente" in mission.message
    assert "vigilancia" in mission.message.lower()
    assert "Primero" in mission.message or "primero" in mission.message
    assert "Propuesta técnica —" not in mission.message.split("\n")[0]


def test_mission_router_price_source_dual_opening():
    """Bootstrap con fuente de precios + técnica: cotización primero, sin titular técnico."""
    state = {
        "name": "VIGILANCIA ISSSTE",
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "technical_post_analysis_hook_pending": True,
        "economic_user_inputs": {"allow_zero_total_base_ack": True},
        "pending_questions": [
            {
                "field": "economic_price_source",
                "type": "economic_validation_blocking",
                "input_mode": "price_source",
                "question": (
                    "Para cerrar la propuesta económica necesito la fuente real de precios o costos "
                    "que usarás en esta licitación. En las bases aparece, por ejemplo, "
                    "**Integración del precio unitario mensual y diario sin el I.V.A. por operario**."
                ),
                "blocking_items": [
                    {
                        "concepto_label": (
                            "Integración del precio unitario mensual y diario sin el I.V.A. por operario"
                        ),
                        "requested_input": "price_source",
                    }
                ],
            }
        ],
        "compliance_master_list": {
            "tecnico": [
                {
                    "nombre": "Propuesta Técnica describiendo especificaciones",
                    "tipo_accion": "generar",
                }
            ],
            "formatos": [],
        },
    }
    mission = resolve_expediente_mission(state)
    assert mission is not None
    assert mission.mission_id == "service_dual_opening"
    assert mission.message.split("\n")[0].startswith("**Cotización pendiente")
    assert "Propuesta técnica —" not in mission.message
    assert "Integración del precio" in mission.message
    assert "metodología" in mission.message.lower() or "personal" in mission.message.lower()


def test_economic_needed_ignores_session_metadata_only():
    from app.services.expediente_mission_router import _economic_mission_needed

    state = {
        "name": "VIGILANCIA ISSSTE",
        "economic_user_inputs": {"allow_zero_total_base_ack": True},
        "compliance_master_list": {"tecnico": [], "formatos": []},
    }
    assert _economic_mission_needed(state) is True


def test_document_shell_excluded_uses_baseline_slots():
    from app.services.technical_slot_mapper import build_technical_slot_inventory

    state = {
        "compliance_master_list": {
            "tecnico": [
                {
                    "nombre": "Propuesta Técnica describiendo especificaciones",
                    "tipo_accion": "generar",
                }
            ],
            "formatos": [],
        }
    }
    slots = build_technical_slot_inventory(state)
    labels = [s.get("label") for s in slots]
    assert "Propuesta Técnica describiendo especificaciones" not in labels
    assert any("Metodología" in str(l) for l in labels)


def test_build_pending_question_has_provenance():
    q = build_document_quality_pending_question(
        gate={"reason": "evidence_match_ratio_below_threshold", "metrics": {}},
        session_state={"name": "Licitación demo"},
        stage="technical",
    )
    prov = q.get("provenance_ui") or {}
    assert prov.get("source") == "document_quality_gate"
    assert q.get("type") == "quality_validation_blocking"


def test_normalize_pipeline_idempotent():
    raw = [
        {
            "type": "document_quality_gate_blocking",
            "field": "document_quality_gate",
            "question": "Debes reclasificar requisitos (generar/presentar_fisico/informativo)",
        }
    ]
    once = normalize_expediente_pending_questions(raw, {"name": "Demo"})
    twice = normalize_expediente_pending_questions(once, {"name": "Demo"})
    assert once[0]["type"] == twice[0]["type"]
    assert_user_visible_clean(str(twice[0].get("question") or ""))
