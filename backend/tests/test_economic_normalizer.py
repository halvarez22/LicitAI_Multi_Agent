from app.services.economic_normalizer import (
    classify_category,
    merge_normalized_payload,
    normalize_line_items,
)


def test_classify_category_basic_keywords():
    assert classify_category("Salario mensual operador") == "mano_obra"
    assert classify_category("Cuotas al I.M.S.S.") == "imss"
    assert classify_category("INFONAVIT") == "impuestos"
    assert classify_category("Aguinaldo anual") == "prestaciones"


def test_normalize_and_merge_payload():
    rows = [
        {
            "id": "li1",
            "concepto_raw": "Salario mensual",
            "concepto_norm": "salario mensual",
            "precio_unitario": 8451.2,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 1,
            "moneda": "MXN",
        },
        {
            "id": "li2",
            "concepto_raw": "Cuotas IMSS",
            "concepto_norm": "cuotas imss",
            "precio_unitario": 2883.56,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 2,
            "moneda": "MXN",
        },
    ]
    payload = normalize_line_items(
        session_id="s1",
        doc_id="d1",
        source_filename="costos.xlsx",
        source_type="excel",
        rows=rows,
        raw_text="TOTAL $0.00 Cantidad de elementos",
    )
    assert payload["summary"]["items_count"] == 2
    assert payload["summary"]["total_detected"] > 0
    assert payload["summary"]["placeholder_signals"]["raw_text_contains_total_0"] is True

    merged = merge_normalized_payload({}, payload)
    root = merged["economic_normalized_data"]
    assert root["summary"]["documents_count"] == 1
    assert root["summary"]["items_count"] == 2
    assert "d1" in root["documents"]
    assert isinstance(root["documents"]["d1"]["normalized_items"][0]["metadata_desglose"], dict)


def test_merge_idempotent_same_document_replaces_not_duplicates():
    rows = [
        {
            "id": "li1",
            "concepto_raw": "Salario mensual",
            "concepto_norm": "salario mensual",
            "precio_unitario": 100.0,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 1,
            "moneda": "MXN",
        }
    ]
    p1 = normalize_line_items(
        session_id="s1",
        doc_id="doc-x",
        source_filename="a.xlsx",
        source_type="excel",
        rows=rows,
        raw_text="TOTAL 0.00 [PENDIENTE]",
    )
    s1 = merge_normalized_payload({}, p1)
    # Simula reproceso forzado del mismo documento con otro total
    rows2 = [dict(rows[0], precio_unitario=200.0)]
    p2 = normalize_line_items(
        session_id="s1",
        doc_id="doc-x",
        source_filename="a.xlsx",
        source_type="excel",
        rows=rows2,
        raw_text="TOTAL 0.00 [PENDIENTE]",
    )
    s2 = merge_normalized_payload(s1, p2)
    root = s2["economic_normalized_data"]
    assert root["summary"]["documents_count"] == 1
    assert root["summary"]["items_count"] == 1
    assert abs(root["summary"]["total_detected"] - 200.0) < 1e-6


def test_inference_avoids_double_count_when_aggregate_matches_base():
    rows = [
        {
            "id": "li1",
            "concepto_raw": "Salario mensual",
            "concepto_norm": "salario mensual",
            "precio_unitario": 100.0,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 1,
            "moneda": "MXN",
        },
        {
            "id": "li2",
            "concepto_raw": "Cuotas IMSS",
            "concepto_norm": "cuotas imss",
            "precio_unitario": 50.0,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 2,
            "moneda": "MXN",
        },
        {
            "id": "li3",
            "concepto_raw": "SUBTOTAL",
            "concepto_norm": "subtotal",
            "precio_unitario": 150.0,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 3,
            "moneda": "MXN",
        },
    ]
    payload = normalize_line_items(
        session_id="s1",
        doc_id="d2",
        source_filename="b.xlsx",
        source_type="excel",
        rows=rows,
        raw_text="SUBTOTAL 150",
    )
    summ = payload["summary"]
    assert summ["inference"]["aggregate_matches_base"] is True
    assert summ["inference"]["total_strategy"] == "base_without_aggregates"
    assert abs(summ["total_detected"] - 150.0) < 1e-6


def test_inference_fallback_uses_max_not_sum_all_rows():
    rows = [
        {
            "id": "li1",
            "concepto_raw": "Salario mensual",
            "concepto_norm": "salario mensual",
            "precio_unitario": 100.0,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 1,
            "moneda": "MXN",
        },
        {
            "id": "li2",
            "concepto_raw": "SUBTOTAL",
            "concepto_norm": "subtotal",
            "precio_unitario": 400.0,
            "cantidad": 1,
            "unidad": "servicio",
            "sheet_name": "Hoja1",
            "row_index": 2,
            "moneda": "MXN",
        },
    ]
    payload = normalize_line_items(
        session_id="s1",
        doc_id="d3",
        source_filename="c.xlsx",
        source_type="excel",
        rows=rows,
        raw_text="SUBTOTAL 400",
    )
    summ = payload["summary"]
    assert summ["inference"]["aggregate_matches_base"] is False
    assert summ["inference"]["total_strategy"] == "max_base_vs_aggregate"
    assert abs(summ["total_detected"] - 400.0) < 1e-6

