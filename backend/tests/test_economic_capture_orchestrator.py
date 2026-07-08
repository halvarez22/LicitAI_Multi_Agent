"""Tests F1: economic_capture_orchestrator HRU."""

from __future__ import annotations

from app.services.chat_gate5_formatter import count_visible_lines
from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.economic_capture_orchestrator import (
    detect_economic_source_conflict,
    try_handle_economic_capture,
)


def test_defer_capture_phrase():
    result = try_handle_economic_capture(
        query="lo pongo en la propuesta economica despues",
        session_state={"name": "Demo"},
        pending_questions=[],
    )
    assert result is not None
    assert result.handled
    assert count_visible_lines(result.respuesta) <= 3
    assert_user_visible_clean(result.respuesta)


def test_economic_status_query():
    state = {
        "name": "Servicios demo",
        "session_line_items": [],
        "capture_matrix_blocks": [],
        "economic_user_inputs": {},
        "pending_questions": [],
    }
    result = try_handle_economic_capture(
        query="que falta cotizar",
        session_state=state,
        pending_questions=[],
    )
    assert result is not None
    assert result.handled
    assert result.economic_capture_v1 is not None
    assert "schema_version" in result.economic_capture_v1


def test_conflict_resolution_prefer_chat():
    state = {
        "_economic_source_conflict": {
            "concept_key": "price_struct_location_leon",
            "label": "León",
            "chat_value": 45250.0,
            "excel_value": 44000.0,
        },
        "economic_user_inputs": {},
        "session_line_items": [],
    }
    result = try_handle_economic_capture(
        query="usa chat",
        session_state=state,
        pending_questions=[],
    )
    assert result is not None
    assert result.handled
    assert result.session_updates["economic_user_inputs"]["price_struct_location_leon"] == 45250.0


def test_detect_source_conflict_universal():
    conflict = detect_economic_source_conflict(
        concept_key="price_struct_service_a_diurno",
        label="Zona A",
        chat_value=100.0,
        excel_value=200.0,
    )
    assert conflict is not None
    assert conflict["concept_key"] == "price_struct_service_a_diurno"
