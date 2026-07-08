#!/usr/bin/env python3
"""
Smoke HRU: copiloto económico (F1) — captura, canónico y conflictos.

Uso:
  cd backend && PYTHONPATH=. python scripts/smoke_economic_chat_capture.py
"""

from __future__ import annotations

import sys

from app.services.chat_gate5_formatter import count_visible_lines
from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.economic_canonical_v1 import build_economic_canonical_v1_from_session
from app.services.economic_capture_orchestrator import try_handle_economic_capture
from app.services.economic_calculation_service import (
    attach_totals_to_canonical,
    build_price_capture_confirmation_message,
    economic_calc_on_capture_enabled,
)
from app.services.economic_post_analysis_hook import run_economic_post_analysis_hook


class _Mem:
    def __init__(self, state: dict):
        self.state = dict(state)

    async def get_session(self, session_id: str):
        return dict(self.state)

    async def save_session(self, session_id: str, updates: dict):
        self.state.update(updates)
        return True


async def _run() -> int:
    errors: list[str] = []

    defer = try_handle_economic_capture(
        query="despues lo pongo en economica",
        session_state={"name": "Smoke demo"},
        pending_questions=[],
    )
    if not defer or not defer.handled:
        errors.append("defer capture no manejado")
    elif count_visible_lines(defer.respuesta) > 3:
        errors.append("defer capture viola Gate 5")

    status = try_handle_economic_capture(
        query="cuantos precios faltan",
        session_state={
            "name": "Smoke demo",
            "session_line_items": [],
            "economic_user_inputs": {},
            "capture_matrix_blocks": [],
        },
        pending_questions=[],
    )
    if not status or not status.economic_capture_v1:
        errors.append("status sin economic_capture_v1")

    rows = [
        {
            "concepto_raw": "Ciudad demo",
            "cantidad": 1.0,
            "extra": {
                "layout": "structured_template",
                "template_kind": "location_price_grid",
                "location_label": "Ciudad demo",
                "source_filename": "anexo_demo.xlsx",
            },
            "sheet_name": "Hoja1",
            "row_index": 2,
        }
    ]
    mem = _Mem({"session_line_items": rows, "pending_questions": []})
    hook = await run_economic_post_analysis_hook(mem, "smoke_sess", mem.state)
    if not hook or hook.get("status") != "queued":
        errors.append("post_analysis hook no encoló precios")

    canon = build_economic_canonical_v1_from_session(mem.state)
    if not canon.get("schema_version"):
        errors.append("canónico sin schema_version")
    if economic_calc_on_capture_enabled():
        if not canon.get("totals"):
            errors.append("F8: canónico sin totals")
        msg_f8 = build_price_capture_confirmation_message(
            session_state={
                **mem.state,
                "economic_user_inputs": {"price_demo": 1000.0},
                "capture_matrix_blocks": [
                    {
                        "matrix_rows": [
                            {"field": "price_demo", "label": "Demo"},
                            {"field": "price_other", "label": "Otro"},
                        ]
                    }
                ],
            },
            label="Demo",
            amount_mxn=1000.0,
            missing_count=1,
        )
        if "Totales actualizados" not in msg_f8:
            errors.append("F8: mensaje captura sin tabla de totales")
        try:
            assert_user_visible_clean(msg_f8)
        except AssertionError as exc:
            errors.append(f"F8 texto prohibido: {exc}")

    for msg in (defer.respuesta if defer else "", status.respuesta if status else ""):
        if msg:
            try:
                assert_user_visible_clean(msg)
            except AssertionError as exc:
                errors.append(f"texto prohibido: {exc}")

    if errors:
        print("SMOKE FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("SMOKE OK: economic chat capture F1 + F8")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(_run()))
