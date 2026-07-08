"""Tests F9: copiloto técnico HRU."""

from __future__ import annotations

from app.services.chat_user_intent import UserChatIntent, resolve_user_intent
from app.services.technical_capture_orchestrator import (
    gate_generar_tecnica_intent,
    parse_technical_capture_phrase,
    try_handle_technical_capture,
)
from app.services.technical_slot_mapper import (
    build_technical_slot_inventory,
    technical_capture_status,
)


def test_build_slots_from_compliance():
    state = {
        "compliance_master_list": {
            "tecnico": [
                {
                    "id": "t1",
                    "nombre": "Metodología de ejecución del servicio",
                    "tipo_accion": "generar",
                },
                {
                    "id": "t2",
                    "nombre": "Personal mínimo por turno",
                    "tipo_accion": "generar",
                },
            ],
            "formatos": [],
        }
    }
    slots = build_technical_slot_inventory(state)
    assert len(slots) >= 2
    kinds = {s["slot_kind"] for s in slots}
    assert "methodology" in kinds
    assert "workforce" in kinds


def test_parse_natural_capture_phrase():
    parsed = parse_technical_capture_phrase(
        "metodología: limpieza hospitalaria por zonas con EPA"
    )
    assert parsed is not None
    assert parsed[0] == "methodology"
    assert "limpieza" in parsed[1]


def test_try_handle_technical_capture_registers_value():
    state = {
        "compliance_master_list": {
            "tecnico": [
                {
                    "nombre": "Metodología de ejecución",
                    "tipo_accion": "generar",
                }
            ],
            "formatos": [],
        },
        "technical_user_inputs": {},
    }
    result = try_handle_technical_capture(
        query="metodologia: limpieza por zonas con EPA",
        session_state=state,
    )
    assert result is not None
    assert result.handled
    assert result.session_updates.get("technical_user_inputs")
    assert result.technical_capture_v1 is not None


def test_gate_generar_tecnica_blocks_incomplete():
    state = {
        "compliance_master_list": {
            "tecnico": [
                {"nombre": "Metodología de ejecución", "tipo_accion": "generar"},
                {"nombre": "Personal mínimo", "tipo_accion": "generar"},
            ],
            "formatos": [],
        },
        "technical_user_inputs": {},
    }
    gate = gate_generar_tecnica_intent(state)
    assert gate.should_block is True
    assert "técnica" in gate.message.lower() or "Metodología" in gate.message


def test_obra_experience_upload_only():
    state = {
        "triage_context": {"tender_category": "OBRA_PUBLICA"},
        "compliance_master_list": {
            "tecnico": [
                {
                    "nombre": "Experiencia en trabajos similares (Anexo T-2)",
                    "tipo_accion": "generar",
                }
            ],
            "formatos": [],
        },
    }
    slots = build_technical_slot_inventory(state)
    assert slots[0]["capture_mode"] == "upload_only"


def test_resolve_capturar_tecnico_intent():
    got = resolve_user_intent("falta metodologia en la propuesta")
    assert got.intent == UserChatIntent.CAPTURAR_TECNICO


def test_resolve_dual_status_intent():
    got = resolve_user_intent("como vamos tecnica y economica")
    assert got.intent == UserChatIntent.VER_ESTADO_DUAL


def test_technical_capture_status_complete():
    state = {
        "compliance_master_list": {
            "tecnico": [
                {"nombre": "Metodología de ejecución", "tipo_accion": "generar"},
            ],
            "formatos": [],
        },
    }
    slots = build_technical_slot_inventory(state)
    key = slots[0]["concept_key"]
    state["technical_user_inputs"] = {key: "Limpieza por zonas"}
    cap = technical_capture_status(state)
    assert cap["capture_complete"] is True
