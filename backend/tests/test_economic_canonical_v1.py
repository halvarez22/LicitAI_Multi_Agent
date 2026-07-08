"""Tests HRU: economic_canonical_v1 merge idempotente."""

from __future__ import annotations

from app.services.economic_canonical_v1 import (
    SCHEMA_VERSION,
    build_economic_canonical_v1_from_session,
    merge_economic_canonical_v1,
    register_canonical_price_update,
)


def test_merge_idempotent_by_concept_key():
    existing = merge_economic_canonical_v1(
        None,
        [
            {
                "concept_key": "price_struct_service_a_diurno",
                "label": "Zona A diurno",
                "amount_mxn": 100.0,
                "status": "captured",
                "source_channel": "user_chat",
                "precedence_rank": 90,
            }
        ],
    )
    merged = merge_economic_canonical_v1(
        existing,
        [
            {
                "concept_key": "price_struct_service_a_diurno",
                "label": "Zona A diurno",
                "amount_mxn": 200.0,
                "status": "captured",
                "source_channel": "user_excel",
                "precedence_rank": 70,
            }
        ],
    )
    item = merged["items"][0]
    assert item["amount_mxn"] == 100.0
    assert item["source_channel"] == "user_chat"


def test_register_canonical_price_update():
    state = {"session_line_items": [], "economic_user_inputs": {}}
    updates = register_canonical_price_update(
        state,
        concept_key="price_struct_location_leon",
        label="León",
        amount_mxn=45250.0,
        source_channel="user_chat",
        original_phrase="Zona A 45250",
    )
    assert updates["economic_user_inputs"]["price_struct_location_leon"] == 45250.0
    assert updates["economic_canonical_v1"]["schema_version"] == SCHEMA_VERSION


def test_build_from_session_structured_rows():
    rows = [
        {
            "concepto_raw": "León",
            "cantidad": 1.0,
            "extra": {
                "layout": "structured_template",
                "template_kind": "location_price_grid",
                "location_label": "León",
                "source_filename": "anexo_precios.xlsx",
            },
            "sheet_name": "ZB",
            "row_index": 3,
        }
    ]
    state = {
        "session_line_items": rows,
        "economic_user_inputs": {"price_struct_location_leon": 45250.0},
    }
    canon = build_economic_canonical_v1_from_session(state)
    assert canon["summary"]["captured"] >= 1
    assert any(i["concept_key"].startswith("price_struct_") for i in canon["items"])
