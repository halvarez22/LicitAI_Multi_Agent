from app.services.chat_economic_matrix import (
    apply_tsv_bulk_to_inputs,
    build_proactive_economic_matrix_welcome,
    format_matrix_blocks_excel_tsv,
    format_matrix_blocks_markdown,
)


def test_format_matrix_markdown():
    blocks = [
        {
            "intro_message": "Precios ZB",
            "column_label": "Costo IVA incl.",
            "matrix_columns": [
                {"key": "label", "title": "Localidad"},
                {"key": "price", "title": "Precio"},
            ],
            "matrix_rows": [
                {"label": "Acámbaro", "price": "", "field": "price_struct_location_acambaro"},
            ],
        }
    ]
    md = format_matrix_blocks_markdown(blocks)
    assert "Acámbaro" in md
    assert "|" in md


def test_tsv_bulk_apply():
    blocks = [
        {
            "matrix_rows": [
                {"label": "Acámbaro", "field": "f1"},
                {"label": "Celaya", "field": "f2"},
            ],
        }
    ]
    text = "Acámbaro\t1325\nCelaya\t1400"
    inputs = {}
    out = apply_tsv_bulk_to_inputs(text, blocks, inputs)
    assert out["applied"]["f1"] == "1325"
    assert inputs["f2"] == 1400.0


def test_excel_tsv_for_clipboard():
    blocks = [
        {
            "source_file": "Anexo III Zona A.xlsx",
            "matrix_columns": [
                {"key": "label", "title": "Ubicación"},
                {"key": "price", "title": "Precio unitario (sin IVA)"},
            ],
            "matrix_rows": [
                {"label": "Zona A | LUNES", "price": "", "field": "f1"},
            ],
        }
    ]
    tsv = format_matrix_blocks_excel_tsv(blocks)
    assert tsv.startswith("\ufeff")
    assert "Anexo / archivo" in tsv
    assert "Zona A | LUNES" in tsv
    assert "Anexo III Zona A.xlsx" in tsv


def test_proactive_welcome_mentions_detection_not_commands():
    blocks = [
        {
            "matrix_columns": [
                {"key": "label", "title": "Zona"},
                {"key": "price", "title": "Precio"},
            ],
            "matrix_rows": [{"label": "Zona A", "price": "", "field": "f1"}],
        }
    ]
    msg = build_proactive_economic_matrix_welcome(blocks, pending_row_count=49)
    assert "Detecté" in msg
    assert "Matriz de precios" in msg
    assert "Copiar para Excel" in msg
    assert "Zona A" in msg
    assert "precios" not in msg.lower() or "uno por uno" in msg


def test_tsv_bulk_single_line_tab():
    blocks = [
        {
            "matrix_rows": [
                {"label": "Zona A", "field": "f_zona_a"},
            ],
        }
    ]
    inputs = {}
    out = apply_tsv_bulk_to_inputs("Zona A\t500", blocks, inputs)
    assert out["applied"]["f_zona_a"] == "500"
