from app.services.structured_economic_price_mapper import build_structured_price_slots


def test_location_price_grid_slot():
    rows = [
        {
            "concepto_raw": "Acámbaro",
            "cantidad": 1.0,
            "extra": {
                "layout": "structured_template",
                "template_kind": "location_price_grid",
                "location_label": "Acámbaro",
                "source_filename": "anexo_zb.xlsx",
            },
        }
    ]
    slots = build_structured_price_slots(rows, {})
    assert len(slots) == 1
    assert slots[0]["field"].startswith("price_struct_location_")
