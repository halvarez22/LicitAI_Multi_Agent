#!/usr/bin/env python3
"""Smoke P0 — expediente guiado HRU (pasos, captura honesta, routing precio)."""

from __future__ import annotations

import sys

from app.services.expediente_guided_service import (
    economic_capture_honest_status,
    find_economic_price_pending_index,
    looks_like_economic_price_reply,
    policy_version,
    resolve_expediente_guided_state,
)


def main() -> int:
    errors: list[str] = []
    if not policy_version().startswith("expediente-guided-v1"):
        errors.append("policy_version")

    if not looks_like_economic_price_reply("5800; 24x24"):
        errors.append("price_reply_detect")

    pending = [
        {"type": "profile_field", "label": "Cuestionamientos Previos"},
        {
            "type": "economic_price",
            "field": "price_vig",
            "label": "Servicios de Vigilancia",
            "capture_guard_schedule": True,
        },
    ]
    if find_economic_price_pending_index(pending, "5800; 24x24", {}) != 1:
        errors.append("preempt_index")

    state = {
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "capture_matrix_blocks": [
            {"matrix_rows": [{"field": "f1", "label": "A"}, {"field": "f2", "label": "B"}]}
        ],
        "economic_user_inputs": {"f1": 1.0, "f2": 2.0},
        "pending_questions": [
            {"type": "economic_price", "field": "price_x", "label": "Extra motor"}
        ],
    }
    cap = economic_capture_honest_status(state)
    if cap.get("capture_complete"):
        errors.append("honest_capture_should_block")
    if int(cap.get("motor_pending_count") or 0) != 1:
        errors.append("motor_pending_count")

    guided = resolve_expediente_guided_state(state, analysis_done_hint=True)
    if guided.get("current_step") != "cotizacion":
        errors.append("guided_step_cotizacion")

    if errors:
        print("FAIL", errors)
        return 1
    print("OK smoke_expediente_guided_p0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
