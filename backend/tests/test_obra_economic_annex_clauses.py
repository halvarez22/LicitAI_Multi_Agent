"""Tests HRU anexos económicos obra E-2/E-3/E-4."""
from __future__ import annotations

from app.services.economic_document_reapply import load_economic_payload
from app.services.obra_economic_annex_clauses import (
    build_obra_e2_catalog_markdown,
    build_obra_e3_annex_markdown,
    build_obra_e4_programa_markdown,
)


def test_obra_e3_no_invented_apu_percentages():
    body = build_obra_e3_annex_markdown(
        concurso="Licitación Pública Num. D/080/2025",
        mapeo_items=[
            {
                "partida": 1,
                "descripcion": "0101 Excavación",
                "precio_unitario": 185.0,
                "importe": 51800.0,
            }
        ],
        req_snippet="Anexo E-3 A Análisis de los precios unitarios factor de salario real E-3 B",
        tabla_precios_basename="TABLA_PRECIOS_UNITARIOS.xlsx",
    )
    low = body.lower()
    assert "anexo e-3" in low
    assert "[consignar]" in low
    assert "71.6%" not in body
    assert "materiales" not in low or "tarjetas" in low
    assert "tabla_precios_unitarios.xlsx" in low


def test_obra_e2_catalog_includes_unit_and_unit_price():
    body = build_obra_e2_catalog_markdown(
        concurso="Licitación Pública Num. D/080/2025",
        mapeo_items=[
            {
                "partida": 1,
                "descripcion": "0101 Excavación",
                "unidad": "m³",
                "cantidad": 10,
                "precio_unitario": 185.0,
                "importe": 1850.0,
            }
        ],
        resumen={
            "obra_breakdown": True,
            "costos_directos": 1000.0,
            "costos_indirectos": 100.0,
            "utilidad": 50.0,
            "subtotal": 1150.0,
            "iva": 184.0,
            "total": 1334.0,
        },
    )
    assert "UNIDAD" in body
    assert "P.U." in body
    assert "m³" in body
    assert "$185.00" in body


def test_obra_e4_gantt_consignar_not_false_present():
    body = build_obra_e4_programa_markdown(
        concurso="Licitación Pública Num. D/080/2025",
        req_snippet="ANEXO E-4 PROGRAMAS DE OBRA 55",
    )
    low = body.lower()
    assert "anexo e-4" in low
    assert "[consignar]" in low
    assert "presento los programas" not in low


def test_extract_obra_e2_requirement_from_corpus():
    from app.services.administrative_letter_clauses import extract_obra_annex_inventory_requirement

    corpus = (
        "ANEXO E-2 Catálogo de conceptos, unidades de medición, cantidades de trabajo. "
        "ANEXO E-3 A Análisis de los precios unitarios"
    )
    req = extract_obra_annex_inventory_requirement(corpus, "E-2")
    assert req
    assert "catálogo" in req.lower() or "catalogo" in req.lower()
    assert "contratos de obras" not in req.lower()


def test_load_economic_payload_obra_breakdown_from_calculator():
    state = {
        "master_proposal_state": {
            "items": [
                {
                    "partida": 1,
                    "concepto": "Obra demo",
                    "cantidad": 1,
                    "precio_unitario": 1000.0,
                    "subtotal": 1000.0,
                }
            ],
            "total_base": 1150.0,
            "grand_total": 1334.0,
            "calculator_result": {
                "costos_directos": 1000.0,
                "costos_indirectos": 100.0,
                "utilidad": 50.0,
                "subtotal_antes_iva": 1150.0,
                "iva_amount": 184.0,
                "indirectos_rate": 0.10,
                "utilidad_rate": 0.05,
                "profile_name": "perfil_obra_publica_v1",
            },
        }
    }
    _, mapeo, resumen = load_economic_payload(state)
    assert len(mapeo) == 1
    assert resumen.get("obra_breakdown") is True
    assert resumen.get("costos_directos") == 1000.0
