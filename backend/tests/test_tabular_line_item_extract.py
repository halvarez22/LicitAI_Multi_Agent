"""Extracción heurística de partidas desde Excel (sin Postgres)."""

import pandas as pd
from docx import Document

from app.services.tabular_line_item_extract import (
    extract_line_items_from_docx_path,
    extract_line_items_from_excel_path,
)


def test_extract_line_items_detecta_concepto_y_precio(tmp_path):
    path = tmp_path / "costos.xlsx"
    df = pd.DataFrame(
        {
            "Concepto": ["Servicio de limpieza", "Vigilancia"],
            "Unidad": ["m2", "hora"],
            "Cantidad": [100, 720],
            "Precio unitario": [12.5, 45.0],
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Partidas", index=False)

    rows = extract_line_items_from_excel_path(str(path), "costos.xlsx")
    assert len(rows) >= 2
    by_concept = {r["concepto_norm"]: r for r in rows}
    assert "servicio de limpieza" in by_concept
    assert by_concept["servicio de limpieza"]["precio_unitario"] == 12.5
    assert by_concept["servicio de limpieza"]["unidad"] == "m2"
    assert "vigilancia" in by_concept
    assert by_concept["vigilancia"]["precio_unitario"] == 45.0


def test_extract_line_items_desde_docx_con_tabla_economica(tmp_path):
    path = tmp_path / "oferta.docx"
    doc = Document()
    table = doc.add_table(rows=1, cols=4)
    table.rows[0].cells[0].text = "Partida"
    table.rows[0].cells[1].text = "Descripcion"
    table.rows[0].cells[2].text = "Unidad"
    table.rows[0].cells[3].text = "Precio Unitario"
    row1 = table.add_row().cells
    row1[0].text = "1"
    row1[1].text = "Suministro e instalacion de paneles solares"
    row1[2].text = "Lote"
    row1[3].text = "$2,586,233.00"
    row2 = table.add_row().cells
    row2[0].text = "2"
    row2[1].text = "Servicio UVIE"
    row2[2].text = "Servicio"
    row2[3].text = "150000"
    doc.save(path)

    rows = extract_line_items_from_docx_path(str(path), "oferta.docx")
    assert len(rows) >= 2
    by_concept = {r["concepto_norm"]: r for r in rows}
    assert "suministro e instalacion de paneles solares" in by_concept
    assert by_concept["suministro e instalacion de paneles solares"]["precio_unitario"] == 2586233.0
    assert by_concept["suministro e instalacion de paneles solares"]["unidad"] == "Lote"
    assert "servicio uvie" in by_concept
    assert by_concept["servicio uvie"]["precio_unitario"] == 150000.0
