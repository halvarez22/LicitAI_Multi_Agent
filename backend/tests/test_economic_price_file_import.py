"""Tests de importación Excel/CSV de cotización económica."""
from __future__ import annotations

import csv
from pathlib import Path

from app.services.economic_price_file_import import import_economic_prices_from_file


def test_import_three_column_excel_export(tmp_path: Path):
    pending = [
        {
            "type": "economic_price",
            "field": "price_f1",
            "label": "ALCOHOL EN GEL (LITRO)",
            "original_item": {"source": "32. Anexo III P1-2 ZA.xlsx"},
        },
        {
            "type": "economic_price",
            "field": "price_f2",
            "label": "Zona A | LUNES A DOMINGO (8 HORAS)",
            "original_item": {"source": "16. Anexo III P 1 Zona A.xlsx"},
        },
    ]
    blocks = [
        {
            "source_file": "32. Anexo III P1-2 ZA.xlsx",
            "matrix_columns": [
                {"key": "label", "title": "Concepto"},
                {"key": "price", "title": "Precio unitario (sin IVA)"},
            ],
            "matrix_rows": [
                {"label": "ALCOHOL EN GEL (LITRO)", "price": "", "field": "price_f1"},
                {"label": "Zona A | LUNES A DOMINGO (8 HORAS)", "price": "", "field": "price_f2"},
            ],
        }
    ]
    csv_path = tmp_path / "cotizacion.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["Anexo / archivo", "Concepto / ubicación", "Precio unitario (sin IVA)"])
        w.writerow(["32. Anexo III P1-2 ZA.xlsx", "ALCOHOL EN GEL (LITRO)", "45"])
        w.writerow(["16. Anexo III P 1 Zona A.xlsx", "Zona A | LUNES A DOMINGO (8 HORAS)", "1850"])

    result = import_economic_prices_from_file(csv_path, blocks, {})
    assert result["applied"]["price_f1"] == 45.0
    assert result["applied"]["price_f2"] == 1850.0
