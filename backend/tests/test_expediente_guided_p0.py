"""Tests HRU P0 — expediente guiado y captura honesta."""

from __future__ import annotations

from app.services.expediente_guided_service import (
    economic_capture_honest_status,
    find_economic_price_pending_index,
    format_honest_capture_summary,
    looks_like_economic_price_reply,
    policy_version,
    resolve_expediente_guided_state,
    split_economic_price_reply,
)


def test_policy_version():
    assert policy_version().startswith("expediente-guided-v1")


def test_split_economic_price_reply_semicolon():
    price, sched = split_economic_price_reply("5800; 24x24")
    assert price == "5800"
    assert sched == "24x24"


def test_looks_like_economic_price_reply():
    assert looks_like_economic_price_reply("5800; 24x24") is True
    assert looks_like_economic_price_reply("hola mundo") is False


def test_honest_status_matrix_full_motor_pending():
    state = {
        "capture_matrix_blocks": [
            {
                "matrix_rows": [
                    {"field": f"f{i}", "label": f"Z{i}"} for i in range(8)
                ]
            }
        ],
        "economic_user_inputs": {f"f{i}": float(i + 1) for i in range(8)},
        "pending_questions": [
            {
                "type": "economic_price",
                "field": "price_vigilancia",
                "label": "Precio de: Servicios de Vigilancia",
                "capture_guard_schedule": True,
            }
        ],
    }
    cap = economic_capture_honest_status(state)
    assert cap["filled"] == 8
    assert cap["total"] == 8
    assert cap["motor_pending_count"] == 1
    assert cap["capture_complete"] is False
    msg = format_honest_capture_summary(cap)
    assert "motor" in msg.lower() or "8" in msg


def test_find_economic_price_pending_prefers_guard_schedule():
    pending = [
        {"type": "profile_field", "field": "cuestionamientos", "label": "Cuestionamientos Previos"},
        {
            "type": "economic_price",
            "field": "price_a",
            "label": "Precio de: Zona A",
            "capture_guard_schedule": False,
        },
        {
            "type": "economic_price",
            "field": "price_vig",
            "label": "Precio de: Servicios de Vigilancia",
            "capture_guard_schedule": True,
        },
    ]
    idx = find_economic_price_pending_index(pending, "5800; 24x24", {})
    assert idx == 2


def test_resolve_guided_step_validar_after_matrix():
    state = {
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "capture_matrix_blocks": [
            {"matrix_rows": [{"field": "f1", "label": "A"}]}
        ],
        "economic_user_inputs": {"f1": 100.0},
        "pending_questions": [],
    }
    guided = resolve_expediente_guided_state(state, analysis_done_hint=True)
    assert guided["current_step"] == "validar_economica"
    assert guided["flags"]["capture_complete"] is True


def test_resolve_guided_materializar_when_validated():
    state = {
        "company_id": "co_mayo",
        "master_profile": {"rfc": "CMT160107S83", "razon_social": "Mayo y Torres"},
        "tasks_completed": [
            {"task": "stage_completed:analysis"},
            {
                "task": "economic_proposal",
                "result": {"status": "complete", "total_base": 100.0},
            },
        ],
        "capture_matrix_blocks": [
            {"matrix_rows": [{"field": "f1", "label": "A"}]}
        ],
        "economic_user_inputs": {"f1": 100.0},
        "pending_questions": [],
    }
    guided = resolve_expediente_guided_state(
        state,
        analysis_done_hint=True,
        company_profile={"rfc": "CMT160107S83"},
        company_exists=True,
    )
    assert guided["current_step"] == "materializar"
    assert guided["primary_cta"]["action_id"] == "TRIGGER_GENERATION_ECONOMIC"
