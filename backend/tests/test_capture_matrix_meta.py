from app.services.economic_capture_matrix_service import (
    build_capture_matrix_blocks,
    build_capture_matrix_meta,
    format_capture_summary_message,
)


def test_capture_matrix_meta_persisted_shape():
    rows = [
        {
            "concepto_raw": city,
            "cantidad": 1.0,
            "extra": {
                "layout": "structured_template",
                "template_kind": "location_price_grid",
                "location_label": city,
                "source_filename": "anexo_zb.xlsx",
                "price_column_header": "COSTO POR ELEMENTO I.V.A INCLUIDO",
            },
        }
        for city in ("Acámbaro", "Celaya", "Salamanca", "León", "Irapuato")
    ]
    blocks = build_capture_matrix_blocks(rows, {})
    meta = build_capture_matrix_meta(blocks, rows)
    assert meta["schema_version"] == "1.0.0"
    assert meta["block_count"] == 1
    assert meta["total_rows"] == 5
    assert "location_price_grid" in meta["template_kinds"]
    assert meta["layouts"][0]["row_dimension"] == "localidades"


def test_format_capture_summary_message():
    msg = format_capture_summary_message({"filled": 23, "total": 23, "capture_complete": True})
    assert "23" in msg
    assert "lista" in msg.lower()
