"""Gate 5 SUPER ISSUE: mensajes compactos y sin códigos crudos."""

from __future__ import annotations

import pytest

from app.services.chat_gate5_formatter import (
    build_compact_meta_status,
    build_compact_session_resume,
    count_visible_lines,
    format_gate5_message,
)
from app.services.chat_stop_reason_map import assert_user_visible_clean


def test_format_gate5_max_three_lines():
    msg = format_gate5_message(
        status="El análisis de bases está listo.",
        detail="Retomamos la licitación.",
        cta="Captura los precios pendientes.",
    )
    assert count_visible_lines(msg) <= 3
    assert "**Siguiente paso:**" in msg


def test_compact_meta_status_gate5():
    msg = build_compact_meta_status(
        stop_reason="MISSING_ECONOMIC_PROPOSAL",
        pending_questions=[
            {"type": "economic_price", "label": "Zona A | L-D", "field": "price_a"},
        ],
        current_idx=0,
    )
    assert count_visible_lines(msg) <= 3
    assert_user_visible_clean(msg)
    assert "MISSING_" not in msg


def test_compact_session_resume_gate5():
    state = {
        "name": "Demo ISAPEG",
        "last_orchestrator_decision": {"stop_reason": "ANALYSIS_COMPLETED"},
        "pending_questions": [
            {"type": "economic_price", "label": "Material X", "field": "price_x"},
        ],
    }
    msg = build_compact_session_resume(state)
    assert count_visible_lines(msg) <= 3
    assert_user_visible_clean(msg)


@pytest.mark.parametrize(
    "stop_reason",
    [
        "ECONOMIC_PRICES_INCOMPLETE",
        "GO_NO_GO_PENDING",
        "MINI_DICTAMEN_BLOCKED",
        "PACKAGING_INCOMPLETE_SOBRES",
        "MISSING_COMPANY_ID",
    ],
)
def test_humanize_orchestrator_stop_reasons(stop_reason: str):
    msg = build_compact_meta_status(stop_reason=stop_reason, pending_questions=[])
    assert_user_visible_clean(msg)
    assert stop_reason not in msg
