"""Tests F1: hook post-análisis económico."""

from __future__ import annotations

import pytest

from app.services.economic_post_analysis_hook import run_economic_post_analysis_hook


class _Mem:
    def __init__(self, state: dict):
        self._state = dict(state)

    async def get_session(self, session_id: str):
        return dict(self._state)

    async def save_session(self, session_id: str, updates: dict):
        self._state.update(updates)
        return True


@pytest.mark.asyncio
async def test_post_analysis_hook_queues_missing_prices(monkeypatch):
    monkeypatch.setattr(
        "app.services.economic_post_analysis_hook.settings.ECONOMIC_POST_ANALYSIS_HOOK_ENABLED",
        True,
    )
    rows = [
        {
            "concepto_raw": "León",
            "cantidad": 1.0,
            "extra": {
                "layout": "structured_template",
                "template_kind": "location_price_grid",
                "location_label": "León",
                "source_filename": "anexo.xlsx",
            },
            "sheet_name": "ZB",
            "row_index": 3,
        }
    ]
    mem = _Mem({"session_line_items": rows, "pending_questions": []})
    out = await run_economic_post_analysis_hook(mem, "sess_demo", mem._state)
    assert out is not None
    assert out.get("missing_count", 0) >= 1
    assert mem._state.get("economic_canonical_v1")
    assert any(
        str(q.get("type") or "").startswith("economic_price")
        for q in (mem._state.get("pending_questions") or [])
    )
