from app.services.economic_coverage_gate import (
    _detect_missing_economic_annexes,
    _expected_annex_has_delivery,
    evaluate_economic_coverage_before_final_ok,
)


def _session_two_annexes(*, with_doc_ids: bool = True) -> dict:
    line_za = {
        "concepto_raw": "CAISES GUANAJUATO",
        "cantidad": 6.0,
        "extra": {
            "layout": "structured_template",
            "template_kind": "service_zone_elements",
            "zone": "A",
            "schedule": "LUNES A VIERNES (8 HORAS)",
            "source_filename": "16. Anexo III P1 Zona A.xlsx",
        },
    }
    line_zb = {
        "concepto_raw": "Acambaro",
        "cantidad": 1.0,
        "extra": {
            "layout": "structured_template",
            "template_kind": "location_price_grid",
            "location_label": "Acambaro",
            "source_filename": "33. Anexo III P1-2 ZB.xlsx",
        },
    }
    if with_doc_ids:
        line_za["document_id"] = "doc-za-001"
        line_zb["document_id"] = "doc-zb-002"

    catalog_items = [
        {
            "doc_id": "doc-za-001",
            "source_filename": "16. Anexo III P1 Zona A.xlsx",
            "filename_key": "anexo iii p1 zona a",
            "document_class": "plantilla_oferta",
            "accion_recomendada": "generar",
            "sobre_inferido": "economico",
        },
        {
            "doc_id": "doc-zb-002",
            "source_filename": "33. Anexo III P1-2 ZB.xlsx",
            "filename_key": "anexo iii p1 2 zb",
            "document_class": "plantilla_oferta",
            "accion_recomendada": "generar",
            "sobre_inferido": "economico",
        },
    ]

    return {
        "session_line_items": [line_za, line_zb],
        "session_template_catalog": {"items": catalog_items},
        "economic_user_inputs": {
            "price_struct_location_acambaro": 100.0,
            "price_struct_service_a_lunes_a_viernes_8_horas": 50.0,
        },
        "tasks_completed": [
            {
                "task": "economic_writing_COMPLETED",
                "result": {
                    "documentos": [
                        {
                            "nombre": "16_Anexo_III_P1_Zona_A_propuesta.xlsx",
                            "source_filename": "16. Anexo III P1 Zona A.xlsx",
                            "source_doc_id": "doc-za-001" if with_doc_ids else None,
                        }
                    ]
                },
            }
        ],
    }


def test_blocks_when_structured_prices_missing():
    session = {
        "session_line_items": [
            {
                "concepto_raw": "Acámbaro",
                "cantidad": 1.0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Acámbaro",
                    "source_filename": "zb.xlsx",
                },
            }
        ],
        "economic_user_inputs": {},
    }
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is not None
    assert block.get("code") == "STRUCTURED_PRICES_PENDING"


def test_blocks_when_economic_annex_imbalance_by_source_doc_id():
    """D.23: desbalance detectado por ``source_doc_id``, no por tokens de nombre."""
    session = _session_two_annexes(with_doc_ids=True)
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is not None
    assert block.get("code") == "ECONOMIC_ANNEX_IMBALANCE"
    assert block.get("match_policy") == "source_doc_id_then_catalog_then_filename_legacy"
    missing = block.get("missing_annexes") or []
    assert len(missing) == 1
    assert missing[0].get("source_doc_id") == "doc-zb-002"
    assert missing[0].get("template_kind") == "location_price_grid"


def test_doc_id_match_does_not_confuse_similar_filenames():
    """Mismo prefijo «Anexo III» no empareja ZB con entregable de ZA si los doc_id difieren."""
    session = _session_two_annexes(with_doc_ids=True)
    generated = session["tasks_completed"][0]["result"]["documentos"]
    coverage_rows = {
        "rows": [
            {
                "source_doc_id": "doc-za-001",
                "source_filename": "16. Anexo III P1 Zona A.xlsx",
                "estado_cobertura": "generado",
                "archivo_entregado": generated[0]["nombre"],
            },
            {
                "source_doc_id": "doc-zb-002",
                "source_filename": "33. Anexo III P1-2 ZB.xlsx",
                "estado_cobertura": "pendiente_generar",
            },
        ]
    }
    missing = _detect_missing_economic_annexes(session, coverage_rows)
    assert len(missing) == 1
    assert missing[0]["source_doc_id"] == "doc-zb-002"


def test_passes_when_both_annexes_delivered_by_doc_id():
    session = _session_two_annexes(with_doc_ids=True)
    session["tasks_completed"][0]["result"]["documentos"].append(
        {
            "nombre": "33_Anexo_III_P1_2_ZB_propuesta.xlsx",
            "source_filename": "33. Anexo III P1-2 ZB.xlsx",
            "source_doc_id": "doc-zb-002",
        }
    )
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is None


def test_legacy_filename_fallback_without_doc_ids():
    """Sesiones sin ``document_id`` siguen usando emparejamiento por nombre."""
    session = _session_two_annexes(with_doc_ids=False)
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is not None
    assert block.get("code") == "ECONOMIC_ANNEX_IMBALANCE"


def test_expected_annex_has_delivery_prefers_doc_id():
    expected = {
        "source_doc_id": "doc-zb-002",
        "source_filename": "33. Anexo III P1-2 ZB.xlsx",
    }
    generated = [
        {
            "nombre": "16_Anexo_III_P1_Zona_A_propuesta.xlsx",
            "source_filename": "16. Anexo III P1 Zona A.xlsx",
            "source_doc_id": "doc-za-001",
        }
    ]
    matched, method = _expected_annex_has_delivery(expected, generated, {})
    assert matched is False
    assert method == ""

    generated.append(
        {
            "nombre": "ZB_out.xlsx",
            "source_filename": "33. Anexo III P1-2 ZB.xlsx",
            "source_doc_id": "doc-zb-002",
        }
    )
    matched, method = _expected_annex_has_delivery(expected, generated, {})
    assert matched is True
    assert method == "generated_source_doc_id"


def test_passes_when_prices_captured():
    field = "price_struct_location_acambaro"
    session = {
        "session_line_items": [
            {
                "concepto_raw": "Acámbaro",
                "cantidad": 1.0,
                "precio_unitario": 100.0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Acámbaro",
                    "source_filename": "zb.xlsx",
                },
            }
        ],
        "economic_user_inputs": {field: 100.0},
    }
    block = evaluate_economic_coverage_before_final_ok(session, "test_sess")
    assert block is None or block.get("code") != "STRUCTURED_PRICES_PENDING"
