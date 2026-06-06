"""Tests de carga y resumen para reaplicación económica."""
from app.services.economic_document_reapply import load_economic_payload


def test_load_economic_payload_from_master_proposal_state():
    state = {
        "master_proposal_state": {
            "items": [
                {
                    "partida": 1,
                    "concepto": "Sistema fotovoltaico",
                    "cantidad": 1,
                    "precio_unitario": 2586233.0,
                    "subtotal": 2586233.0,
                }
            ],
            "total_base": 2586233.0,
            "grand_total": 3000030.28,
            "currency": "MXN",
        },
        "critical_dates": [{"label": "Recepción de propuestas", "date": "2026-04-23"}],
    }
    economic_data, mapeo, resumen = load_economic_payload(state)
    assert economic_data is not None
    assert len(mapeo) == 1
    assert resumen["subtotal"] == 2586233.0
    assert resumen["total"] == 3000030.28
    assert resumen["iva"] == round(3000030.28 - 2586233.0, 2)


def test_load_economic_payload_empty_items():
    state = {"master_proposal_state": {"items": []}}
    economic_data, mapeo, resumen = load_economic_payload(state)
    assert mapeo == []
    assert resumen == {}
