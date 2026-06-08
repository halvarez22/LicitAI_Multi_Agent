"""
Convergencia tri-canal: UI (mass_save) | CSV import | TSV chat → mismo estado canónico (Ítem D.14).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict

from app.services.chat_economic_matrix import apply_tsv_bulk_to_inputs
from app.services.economic_capture_matrix_service import build_capture_matrix_blocks
from app.services.economic_price_file_import import import_economic_prices_from_file


def _zb_fixture_rows() -> list:
    cities = ("Acámbaro", "Celaya", "Salamanca", "León", "Irapuato", "Silao")
    return [
        {
            "concepto_raw": city,
            "cantidad": 1.0,
            "extra": {
                "layout": "structured_template",
                "template_kind": "location_price_grid",
                "location_label": city,
                "source_filename": "33. Anexo III P1-2 ZB.xlsx",
                "price_column_header": "COSTO POR ELEMENTO I.V.A INCLUIDO",
                "price_column_index": 3,
                "sheet_name": "ZB",
                "header_row_index": 2,
            },
            "sheet_name": "ZB",
            "row_index": i + 3,
        }
        for i, city in enumerate(cities)
    ]


def _canonical_prices(inputs: Dict[str, Any]) -> Dict[str, float]:
    """Normaliza economic_user_inputs a field→float (ignora metadatos)."""
    out: Dict[str, float] = {}
    skip = {"concept_prices", "allow_zero_total_base_ack", "economic_matrix_bulk"}
    for key, val in (inputs or {}).items():
        if str(key) in skip:
            continue
        if val is None or str(val).strip() == "":
            continue
        try:
            out[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    bucket = inputs.get("concept_prices") if isinstance(inputs.get("concept_prices"), dict) else {}
    for key, val in bucket.items():
        try:
            out[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def _price_map(blocks: list) -> Dict[str, float]:
    prices = {
        str(r["field"]): 100.0 + i * 10
        for block in blocks
        for i, r in enumerate(block.get("matrix_rows") or [])
        if r.get("field")
    }
    return prices


def test_tsv_csv_ui_converge_to_same_canonical_state(tmp_path: Path):
    rows = _zb_fixture_rows()
    blocks = build_capture_matrix_blocks(rows, {})
    assert len(blocks) == 1
    expected = _price_map(blocks)

    # Canal TSV (chat)
    inputs_tsv: Dict[str, Any] = {}
    tsv_lines = ["Ubicación\tPrecio"]
    for block in blocks:
        for row in block.get("matrix_rows") or []:
            field = str(row.get("field") or "")
            if not field:
                continue
            tsv_lines.append(f"{row.get('label')}\t{expected[field]}")
    apply_tsv_bulk_to_inputs("\n".join(tsv_lines), blocks, inputs_tsv)
    canon_tsv = _canonical_prices(inputs_tsv)

    # Canal CSV (import archivo)
    csv_path = tmp_path / "cotizacion.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["Anexo / archivo", "Concepto / ubicación", "Precio unitario (IVA incl.)"])
        for block in blocks:
            for row in block.get("matrix_rows") or []:
                field = str(row.get("field") or "")
                if field:
                    w.writerow([block["source_file"], row["label"], expected[field]])
    result_csv = import_economic_prices_from_file(csv_path, blocks, {})
    canon_csv = _canonical_prices(result_csv.get("economic_user_inputs") or {})

    # Canal UI (mass_save directo a inputs)
    inputs_ui: Dict[str, Any] = {"concept_prices": dict(expected)}
    for field, price in expected.items():
        inputs_ui[field] = price
    canon_ui = _canonical_prices(inputs_ui)

    assert canon_tsv == expected
    assert canon_csv == expected
    assert canon_ui == expected
    assert canon_tsv == canon_csv == canon_ui


def test_matrix_rows_include_provenance_ui():
    rows = _zb_fixture_rows()[:3]
    blocks = build_capture_matrix_blocks(rows, {})
    assert blocks
    for block in blocks:
        for row in block.get("matrix_rows") or []:
            prov = row.get("provenance_ui")
            assert isinstance(prov, dict)
            assert prov.get("source_file")
            assert prov.get("column_role") == "unit_price_iva_included"
            assert "badge" in prov
