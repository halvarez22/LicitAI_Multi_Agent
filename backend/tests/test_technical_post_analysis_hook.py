"""Tests F9.5: technical_post_analysis_hook."""

from __future__ import annotations

from app.services.technical_post_analysis_hook import run_technical_post_analysis_hook


class _Mem:
    def __init__(self, state: dict):
        self.state = dict(state)

    async def get_session(self, session_id: str):
        return dict(self.state)

    async def save_session(self, session_id: str, updates: dict):
        self.state.update(updates)
        return True


async def test_hook_queues_technical_slots():
    mem = _Mem(
        {
            "compliance_master_list": {
                "tecnico": [
                    {"nombre": "Metodología de ejecución", "tipo_accion": "generar"},
                    {"nombre": "Personal mínimo", "tipo_accion": "generar"},
                ],
                "formatos": [],
            }
        }
    )
    out = await run_technical_post_analysis_hook(mem, "sess", mem.state)
    assert out and out.get("status") == "queued"
    assert mem.state.get("technical_capture_mode")
    assert mem.state.get("technical_post_analysis_hook_pending") is True
