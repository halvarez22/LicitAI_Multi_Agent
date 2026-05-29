from app.services.structured_economic_price_mapper import (
    apply_structured_price_inputs,
    build_structured_price_slots,
)


def _structured_service_row(*, doc_id: str, row_index: int, qty: float, zone: str, schedule: str, concepto: str):
    return {
        "document_id": doc_id,
        "concepto_raw": concepto,
        "concepto_norm": concepto.lower(),
        "unidad": "ELEMENTO",
        "cantidad": qty,
        "precio_unitario": 0.0,
        "sheet_name": f"PARTIDA 1 ZONA {zone}",
        "row_index": row_index,
        "extra": {
            "layout": "structured_template",
            "template_kind": "service_zone_elements",
            "zone": zone,
            "schedule": schedule,
            "source_filename": f"zona_{zone}.xlsx",
            "price_input_pending": True,
        },
    }


def _structured_material_row(*, doc_id: str, row_index: int, qty: float, concepto: str, unidad: str, zone: str):
    return {
        "document_id": doc_id,
        "concepto_raw": concepto,
        "concepto_norm": concepto.lower(),
        "unidad": unidad,
        "cantidad": qty,
        "precio_unitario": 0.0,
        "sheet_name": f"PARTIDA 2 ZONA {zone}",
        "row_index": row_index,
        "extra": {
            "layout": "structured_template",
            "template_kind": "monthly_material_requirement",
            "zone": zone,
            "source_filename": f"p12_{zone}.xlsx",
            "price_input_pending": True,
        },
    }


def _material_reference_row(*, doc_id: str, row_index: int, concepto: str):
    return {
        "document_id": doc_id,
        "concepto_raw": concepto,
        "concepto_norm": concepto.lower(),
        "unidad": None,
        "cantidad": None,
        "precio_unitario": 0.0,
        "sheet_name": "ANEXO III-H.a",
        "row_index": row_index,
        "extra": {
            "source_filename": "matriz_cantidades_materiales.xlsx",
        },
    }


def _support_noise_row(*, doc_id: str, row_index: int, concepto: str, source_filename: str, sheet_name: str):
    return {
        "document_id": doc_id,
        "concepto_raw": concepto,
        "concepto_norm": concepto.lower(),
        "unidad": None,
        "cantidad": None,
        "precio_unitario": 1.0,
        "sheet_name": sheet_name,
        "row_index": row_index,
        "extra": {
            "source_filename": source_filename,
        },
    }


def test_build_structured_price_slots_group_service_and_material_rows():
    rows = [
        _structured_service_row(
            doc_id="doc-1",
            row_index=11,
            qty=6,
            zone="A",
            schedule="LUNES A VIERNES (8 HORAS)",
            concepto="CAISES GUANAJUATO",
        ),
        _structured_service_row(
            doc_id="doc-2",
            row_index=12,
            qty=1,
            zone="A",
            schedule="LUNES A VIERNES (8 HORAS)",
            concepto="UMAPS ARPEROS",
        ),
        _structured_material_row(
            doc_id="doc-3",
            row_index=3,
            qty=1528,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
            unidad="KILO",
            zone="A",
        ),
        _structured_material_row(
            doc_id="doc-4",
            row_index=3,
            qty=1400,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
            unidad="KILO",
            zone="B",
        ),
        _material_reference_row(
            doc_id="doc-h",
            row_index=14,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
        ),
    ]

    slots = build_structured_price_slots(rows)
    assert len(slots) == 2

    service = slots[0]
    assert service["slot_type"] == "service_zone_elements"
    assert service["rows_count"] == 2
    assert service["quantity_total"] == 7.0
    assert "zona a" in service["concept_label"].lower()

    material = slots[1]
    assert material["slot_type"] == "monthly_material_requirement"
    assert material["rows_count"] == 2
    assert material["quantity_total"] == 2928.0
    assert "bolsa de plástico chica 55x60" in material["concept_label"].lower()
    assert material["quantity_support_source_name"] == "matriz_cantidades_materiales.xlsx"
    assert material["quantity_support_sheet_name"] == "ANEXO III-H.a"
    assert material["quantity_support_row_index"] == 14


def test_build_structured_price_slots_prefers_broader_support_document():
    rows = [
        _structured_material_row(
            doc_id="doc-3",
            row_index=3,
            qty=1528,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
            unidad="KILO",
            zone="A",
        ),
        _structured_material_row(
            doc_id="doc-4",
            row_index=39,
            qty=129,
            concepto="ALCOHOL EN GEL",
            unidad="LITRO",
            zone="A",
        ),
        _material_reference_row(
            doc_id="doc-narrow",
            row_index=14,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
        ),
        _support_noise_row(
            doc_id="doc-broad",
            row_index=10,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
            source_filename="soporte_amplio.xlsx",
            sheet_name="MATERIALES",
        ),
        _support_noise_row(
            doc_id="doc-broad",
            row_index=11,
            concepto="ALCOHOL EN GEL",
            source_filename="soporte_amplio.xlsx",
            sheet_name="MATERIALES",
        ),
        _support_noise_row(
            doc_id="doc-broad",
            row_index=200,
            concepto="OTRO MATERIAL",
            source_filename="soporte_amplio.xlsx",
            sheet_name="ZONA A",
        ),
        _support_noise_row(
            doc_id="doc-broad",
            row_index=201,
            concepto="OTRO MATERIAL 2",
            source_filename="soporte_amplio.xlsx",
            sheet_name="ZONA B",
        ),
    ]

    slots = build_structured_price_slots(rows)
    support_sources = {
        slot["field"]: slot.get("quantity_support_source_name")
        for slot in slots
        if slot["slot_type"] == "monthly_material_requirement"
    }
    assert support_sources["price_struct_material_bolsa_de_plastico_chica_55x60"] == "soporte_amplio.xlsx"
    assert support_sources["price_struct_material_alcohol_en_gel"] == "soporte_amplio.xlsx"


def test_apply_structured_price_inputs_populates_matching_rows():
    rows = [
        _structured_service_row(
            doc_id="doc-1",
            row_index=11,
            qty=6,
            zone="A",
            schedule="LUNES A VIERNES (8 HORAS)",
            concepto="CAISES GUANAJUATO",
        ),
        _structured_material_row(
            doc_id="doc-3",
            row_index=3,
            qty=1528,
            concepto="BOLSA DE PLÁSTICO CHICA 55X60",
            unidad="KILO",
            zone="A",
        ),
    ]
    slots = build_structured_price_slots(rows)
    concept_prices = {
        slots[0]["field"]: 123.45,
        slots[1]["concept_label"]: 22.7,
    }

    updated = apply_structured_price_inputs(rows, concept_prices)
    assert updated[0]["precio_unitario"] == 123.45
    assert updated[1]["precio_unitario"] == 22.7
    assert updated[0]["extra"]["price_input_applied"] is True
    assert updated[1]["extra"]["price_input_source"] == "economic_user_inputs"
