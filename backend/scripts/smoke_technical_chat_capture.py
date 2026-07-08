#!/usr/bin/env python3
"""
Smoke HRU F9: copiloto técnico — slots, captura y gate generar.

Uso:
  cd backend && PYTHONPATH=. python scripts/smoke_technical_chat_capture.py
"""

from __future__ import annotations

import asyncio
import sys

from app.services.chat_stop_reason_map import assert_user_visible_clean
from app.services.technical_canonical_v1 import build_technical_canonical_v1_from_session
from app.services.technical_capture_orchestrator import try_handle_technical_capture
from app.services.technical_post_analysis_hook import run_technical_post_analysis_hook


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

    state = {
        "name": "Smoke técnico",
        "compliance_master_list": {
            "tecnico": [
                {"nombre": "Metodología de ejecución", "tipo_accion": "generar"},
                {"nombre": "Personal por turno", "tipo_accion": "generar"},
            ],
            "formatos": [],
        },
    }
    mem = _Mem(state)
    hook = await run_technical_post_analysis_hook(mem, "smoke_tech", mem.state)
    if not hook or hook.get("status") != "queued":
        errors.append("post_analysis hook no encoló slots técnicos")

    cap = try_handle_technical_capture(
        query="metodologia: limpieza por zonas con EPA",
        session_state=mem.state,
    )
    if not cap or not cap.handled:
        errors.append("captura natural no manejada")
    elif not cap.technical_capture_v1:
        errors.append("sin technical_capture_v1 en respuesta")

    merged = {**mem.state, **(cap.session_updates if cap else {})}
    canon = build_technical_canonical_v1_from_session(merged)
    if not canon.get("schema_version"):
        errors.append("canónico técnico sin schema_version")

    for msg in (cap.respuesta if cap else "",):
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
    print("SMOKE OK: technical chat capture F9")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
