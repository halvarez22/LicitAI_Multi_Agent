"""Tests de sincronización económica tras ingest tabular."""

import pytest

from app.services.economic_tabular_ingest_sync import (
    filter_reliable_pricing_rows,
    has_price_source_tabular_evidence,
    sync_economic_pending_after_tabular_ingest,
    tech_requirements_from_tabular_pricing,
)

class _MemStub:
    def __init__(self, session_state=None, line_items=None):
        self._session = dict(session_state or {})
        self._line_items = list(line_items or [])
        self.saved = False

    async def get_line_items_for_session(self, session_id: str):
        return list(self._line_items)

    async def get_session(self, session_id: str):
        return dict(self._session)

    async def save_session(self, session_id: str, state):
        self._session = dict(state)
        self.saved = True


@pytest.mark.asyncio
async def test_sync_clears_price_source_when_reliable_rows_exist():
    mem = _MemStub(
        session_state={
            "pending_questions": [
                {
                    "field": "economic_price_source",
                    "type": "economic_validation_blocking",
                    "input_mode": "price_source",
                }
            ]
        },
        line_items=[
            {
                "id": "li-1",
                "concepto_raw": "Panel solar",
                "concepto_norm": "panel solar",
                "precio_unitario": 1500.0,
                "cantidad": 1,
                "extra": {"price_column_index": 3},
            }
        ],
    )
    out = await sync_economic_pending_after_tabular_ingest(mem, "s1")
    assert out["reliable_count"] == 1
    assert out["cleared_price_source"] is True
    assert mem.saved is True
    pending = mem._session.get("pending_questions") or []
    assert not any(str(q.get("field")) == "economic_price_source" for q in pending)


@pytest.mark.asyncio
async def test_sync_clears_price_source_for_raw_calculation_breakdown():
    """Desglose Anexo 8 (raw_calculation) debe cerrar price_source con >=2 filas priced."""
    rows = [
        {
            "id": "li-calc-1",
            "concepto_raw": "Salario:",
            "precio_unitario": 278.0,
            "extra": {
                "source_filename": "CALCULO COSTO.xlsx",
                "layout": "raw_calculation",
            },
        },
        {
            "id": "li-calc-2",
            "concepto_raw": "Prestaciones:",
            "precio_unitario": 120.0,
            "extra": {
                "source_filename": "CALCULO COSTO.xlsx",
                "layout": "raw_calculation",
            },
        },
    ]
    mem = _MemStub(
        session_state={
            "pending_questions": [
                {
                    "field": "economic_price_source",
                    "type": "economic_validation_blocking",
                    "input_mode": "price_source",
                }
            ]
        },
        line_items=rows,
    )
    out = await sync_economic_pending_after_tabular_ingest(mem, "s_vig")
    assert has_price_source_tabular_evidence(rows) is True
    assert out["reliable_count"] == 0
    assert out["cleared_price_source"] is True
    pending = mem._session.get("pending_questions") or []
    assert not any(str(q.get("field")) == "economic_price_source" for q in pending)


@pytest.mark.asyncio
async def test_sync_noop_single_raw_calculation_row():
    """Una sola fila raw_calculation no debe cerrar price_source (anti falso positivo)."""
    rows = [
        {
            "id": "li-calc-1",
            "concepto_raw": "Salario:",
            "precio_unitario": 278.0,
            "extra": {"layout": "raw_calculation"},
        }
    ]
    mem = _MemStub(
        session_state={
            "pending_questions": [
                {"field": "economic_price_source", "input_mode": "price_source"}
            ]
        },
        line_items=rows,
    )
    assert has_price_source_tabular_evidence(rows) is False
    out = await sync_economic_pending_after_tabular_ingest(mem, "s_single")
    assert out["cleared_price_source"] is False


def test_has_price_source_structured_catalog_row():
    """Partida con price_column_index (catálogo ISAPEG/UNAQ-style) acredita fuente."""
    rows = [
        {
            "id": "li-oferta",
            "concepto_raw": "Servicio de limpieza",
            "precio_unitario": 1500.0,
            "extra": {"price_column_index": 4, "source_filename": "catalogo.xlsx"},
        }
    ]
    assert has_price_source_tabular_evidence(rows) is True
    assert filter_reliable_pricing_rows(rows)


@pytest.mark.asyncio
async def test_sync_noop_without_positive_prices():
    mem = _MemStub(
        session_state={
            "pending_questions": [
                {"field": "economic_price_source", "input_mode": "price_source"}
            ]
        },
        line_items=[
            {
                "id": "li-1",
                "concepto_raw": "Servicio",
                "precio_unitario": 0.0,
                "extra": {"layout": "structured_template"},
            }
        ],
    )
    out = await sync_economic_pending_after_tabular_ingest(mem, "s1")
    assert out["reliable_count"] == 0
    assert out["cleared_price_source"] is False


def test_tech_requirements_from_tabular_pricing():
    rows = filter_reliable_pricing_rows(
        [
            {
                "id": "x1",
                "concepto_raw": "Instalación",
                "precio_unitario": 99.0,
                "extra": {},
            }
        ]
    )
    reqs = tech_requirements_from_tabular_pricing(rows)
    assert len(reqs) == 1
    assert reqs[0]["id"] == "x1"
    assert "Instalación" in reqs[0]["descripcion"]
