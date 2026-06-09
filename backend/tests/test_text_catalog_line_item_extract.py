"""Extracción de catálogo obra desde texto plano (TXT / PDF nativo)."""

from __future__ import annotations

from app.services.tabular_line_item_extract import extract_line_items_from_text_blob

BARDA_INLINE_TSV = """
1\t0101\tExcavación manual o mecánica para cimiento de barda, profundidad promedio 0.80 m\tm³\t280\t185.00\t51,800.00
2\t0201\tCimiento de concreto armado f'c=150 kg/cm², con armado de acero\tm³\t85\t3,250.00\t276,250.00
3\t0301\tColumna de concreto armado cada 3.00 m, f'c=250 kg/cm², con armado\tm³\t42\t4,850.00\t203,700.00
"""

BARDA_OCR_MULTILINE = """
1
0101
Excavación manual
o mecánica para
cimiento de barda,
profundidad
promedio 0.80 m
m³
280
185.00
51,800.00
2
0201
Cimiento de
concreto armado
f'c=150 kg/cm², con
armado de acero
m³
85
3,250.00
276,250.00
"""


def test_extract_inline_tsv_catalog_rows():
    rows = extract_line_items_from_text_blob(BARDA_INLINE_TSV, "catalogo.txt")
    assert len(rows) >= 2
    assert any("0101" in str(r.get("concepto_raw") or "") for r in rows)
    assert any(float(r.get("precio_unitario") or 0) == 185.0 for r in rows)


def test_extract_ocr_multiline_catalog_rows():
    rows = extract_line_items_from_text_blob(BARDA_OCR_MULTILINE, "catalogo.pdf")
    assert len(rows) >= 2
    claves = {str((r.get("extra") or {}).get("clave") or "") for r in rows}
    assert "0101" in claves
    assert "0201" in claves
    assert all(float(r.get("precio_unitario") or 0) > 0 for r in rows)


def test_extract_ignores_single_stray_number():
    rows = extract_line_items_from_text_blob("Total propuesta 2150000", "resumen.txt")
    assert rows == []


BARDA_TAIL_OCR = """
7
0701
Pintura vinílica en
dos manos color
blanco sobre repello
m²
2,900
95.00
275,500.00
8
0801
Suministro y
colocación de puerta
peatonal de metal de
1.20 x 2.20 m
pza
2
18,500.00 37,000.00
9
0901 Suministro y
colocación de puerta pza
1
48,000.00 48,000.00
10
1001
Limpieza final,
retiro de escombro y
nivelación de
terreno
m²
1,600
65.00
104,000.00
"""


def test_extract_barda_tail_with_dual_price_line_and_clave_inline():
    rows = extract_line_items_from_text_blob(BARDA_TAIL_OCR, "catalogo.pdf")
    claves = {str((r.get("extra") or {}).get("clave") or "") for r in rows}
    assert "0801" in claves
    assert "0901" in claves
    by_clave = {str((r.get("extra") or {}).get("clave")): r for r in rows}
    assert float(by_clave["0801"]["precio_unitario"]) == 18500.0
    assert float(by_clave["0801"]["cantidad"]) == 2.0
    assert float(by_clave["0901"]["precio_unitario"]) == 48000.0
    assert float(by_clave["0901"]["cantidad"]) == 1.0
