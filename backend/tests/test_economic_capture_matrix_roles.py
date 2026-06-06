"""Matriz de captura con roles de columna semánticos (Ítem D)."""

from app.services.economic_capture_matrix_service import build_capture_matrix_blocks


def test_matrix_uses_iva_included_role_from_header():
    rows = []
    for city in ("Acámbaro", "Celaya", "Salamanca", "León", "Irapuato", "Silao"):
        rows.append(
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
        )
    blocks = build_capture_matrix_blocks(rows, {})
    assert len(blocks) == 1
    assert blocks[0]["column_role"] == "unit_price_iva_included"
    assert "iva incluido" in blocks[0]["column_label"].lower()
    assert "Acámbaro" in blocks[0]["intro_message"]
