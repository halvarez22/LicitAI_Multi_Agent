#!/usr/bin/env python3
"""
Smoke F11 — briefing de convocatoria y apertura unificada (HRU piloto).
"""

from __future__ import annotations

import sys

from app.services.chat_gate5_formatter import count_visible_lines
from app.services.chat_opening_orchestrator import resolve_chat_opening
from app.services.convocatoria_briefing_service import (
    build_convocatoria_briefing_canonical_v1,
    policy_version,
)
from app.services.convocatoria_briefing_ux import render_opening_message


def _vigilancia_state() -> dict:
    return {
        "name": "Vigilancia HRU smoke",
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "session_line_items": [
            {"concepto_raw": "Entrada Principal", "extra": {"location_label": "Entrada Principal"}}
        ],
        "economic_user_inputs": {},
        "compliance_master_list": {
            "administrativo": [{"nombre": "Constancia de visita", "tipo_accion": "presentar_fisico"}],
            "tecnico": [{"nombre": "Organigrama", "tipo_accion": "generar"}],
            "economico": [{"nombre": "Cédula económica", "tipo_accion": "generar"}],
        },
        "technical_post_analysis_hook_pending": True,
    }


def main() -> int:
    errors: list[str] = []
    if not policy_version().startswith("convocatoria-briefing-v1"):
        errors.append("policy_version")
    state = _vigilancia_state()
    briefing = build_convocatoria_briefing_canonical_v1(state)
    if briefing.get("recommended_first_track") != "economic":
        errors.append("first_track_not_economic")
    if len(briefing.get("blocks") or []) != 3:
        errors.append("blocks_count")
    msg = render_opening_message(session_state=state, briefing=briefing)
    if "convocante" not in msg.lower():
        errors.append("opening_missing_convocante")
    if "price_source" in msg.lower():
        errors.append("jargon_price_source")
    if count_visible_lines(msg) > 4:
        errors.append("gate5_briefing_lines")
    opening = resolve_chat_opening(
        session_state={**state, "convocatoria_briefing_v1": briefing},
        pending_questions=[],
        current_idx=0,
        user_query="",
        company_id="smoke-co",
    )
    if opening is None:
        errors.append("orchestrator_none")
    if errors:
        print("SMOKE F11 FAIL:", ", ".join(errors))
        return 1
    print("SMOKE F11 OK — track=economic lines=", count_visible_lines(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
