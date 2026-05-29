from app.services.economic_coverage_gate import evaluate_economic_coverage_before_final_ok


def test_blocks_when_structured_prices_missing():
    session = {
        "session_line_items": [
            {
                "concepto_raw": "Acámbaro",
                "cantidad": 1.0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Acámbaro",
                    "source_filename": "zb.xlsx",
                },
            }
        ],
        "economic_user_inputs": {},
    }
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is not None
    assert block.get("code") == "STRUCTURED_PRICES_PENDING"


def test_passes_when_prices_captured():
    field = "price_struct_location_acambaro"
    session = {
        "session_line_items": [
            {
                "concepto_raw": "Acámbaro",
                "cantidad": 1.0,
                "precio_unitario": 100.0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Acámbaro",
                    "source_filename": "zb.xlsx",
                },
            }
        ],
        "economic_user_inputs": {field: 100.0},
    }
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is None or block.get("code") != "STRUCTURED_PRICES_PENDING"
