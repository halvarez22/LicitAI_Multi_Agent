"""Conflictos de totales entre fuentes económicas normalizadas."""

from __future__ import annotations

from app.services.economic_normalizer import merge_normalized_payload, normalize_line_items


def _payload(doc_id: str, filename: str, rows: list[dict], raw: str = "") -> dict:
    return normalize_line_items(
        session_id="s1",
        doc_id=doc_id,
        source_filename=filename,
        source_type="text_catalog",
        rows=rows,
        raw_text=raw,
    )


def test_merge_detects_conflicting_economic_totals():
    cat_rows = [
        {
            "id": "a",
            "concepto_raw": "0101 Excavación",
            "concepto_norm": "0101 excavacion",
            "precio_unitario": 185.0,
            "cantidad": 280,
            "unidad": "m3",
            "moneda": "MXN",
        },
        {
            "id": "b",
            "concepto_raw": "0201 Cimiento",
            "concepto_norm": "0201 cimiento",
            "precio_unitario": 3250.0,
            "cantidad": 85,
            "unidad": "m3",
            "moneda": "MXN",
        },
    ]
    letter_rows = [
        {
            "id": "c",
            "concepto_raw": "Total propuesta resumen",
            "concepto_norm": "total propuesta resumen",
            "precio_unitario": 2150000.0,
            "cantidad": 1,
            "unidad": "global",
            "moneda": "MXN",
        },
        {
            "id": "d",
            "concepto_raw": "IVA incluido",
            "concepto_norm": "iva incluido",
            "precio_unitario": 344000.0,
            "cantidad": 1,
            "unidad": "global",
            "moneda": "MXN",
        },
    ]
    state: dict = {}
    state = merge_normalized_payload(state, _payload("d1", "catalogo.pdf", cat_rows))
    state = merge_normalized_payload(state, _payload("d2", "propuesta.pdf", letter_rows))
    summary = (state.get("economic_normalized_data") or {}).get("summary") or {}
    conflicts = summary.get("source_total_conflicts") or []
    assert conflicts, "Debe detectar conflicto entre catálogo detallado y carta resumen"
    assert summary.get("canonical_source") == "catalogo.pdf"
