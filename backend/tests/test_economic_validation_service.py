import pytest
from unittest.mock import AsyncMock

from app.economic_validation.service import (
    get_latest_analysis_and_economic,
    refresh_economic_validations_for_session,
)


def test_get_latest_analysis_and_economic():
    st = {
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {"data": {"cronograma": {}}}},
            {"task": "economic_proposal", "result": {"items": [{"x": 1}], "total_base": 10, "grand_total": 11.6}},
        ]
    }
    a, e = get_latest_analysis_and_economic(st)
    assert "data" in a
    assert "items" in e


@pytest.mark.asyncio
async def test_refresh_economic_validations_for_session():
    store = {
        "sx": {
            "name": "ISSSTE demo",
            "tasks_completed": [
                {"task": "stage_completed:analysis", "result": {"data": {"reglas_economicas": {}}}},
                {
                    "task": "economic_proposal",
                    "result": {
                        "items": [{"concepto": "A", "cantidad": 1, "precio_unitario": 10, "subtotal": 10}],
                        "currency": "MXN",
                        "total_base": 10,
                        "grand_total": 11.6,
                    },
                },
            ],
        }
    }

    class Mem:
        def __init__(self):
            self.get_session = AsyncMock(side_effect=lambda sid: store.get(sid))
            self.save_session = AsyncMock(side_effect=lambda sid, data: store.update({sid: data}) or True)

    mem = Mem()
    out = await refresh_economic_validations_for_session(mem, "sx")
    assert out.perfil_usado in ("generic", "health_sector_annex_like", "issste_2024_like")
    ep = store["sx"]["tasks_completed"][-1]["result"]
    assert "validation_result" in ep
