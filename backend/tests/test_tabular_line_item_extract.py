"""Extracción heurística de partidas desde Excel (sin Postgres)."""

import pandas as pd

from app.services.tabular_line_item_extract import extract_line_items_from_excel_path


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
