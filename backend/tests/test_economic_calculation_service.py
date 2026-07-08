"""Tests F8: economic_calculation_service HRU."""

from __future__ import annotations

import pytest

from app.services.economic_calculation_service import (
    attach_totals_to_canonical,
    build_price_capture_confirmation_message,
    compute_quotation_totals_from_canonical,
    economic_calc_on_capture_enabled,
    format_money_mxn,
    resolve_iva_context,
)
from app.services.economic_capture_orchestrator import gate_generar_economica_intent as gate_from_orch


def test_format_money_mxn():
    assert format_money_mxn(45250) == "$45,250.00 MXN"


def test_compute_totals_with_default_iva():
    canonical = {
        "items": [
            {"status": "captured", "amount_mxn": 10000.0},
            {"status": "captured", "amount_mxn": 2500.0},
            {"status": "pending", "amount_mxn": 500.0},
        ]
    }
    totals = compute_quotation_totals_from_canonical(canonical, session_state={})
    assert totals["subtotal"] == 12500.0
    assert totals["iva"] == 2000.0
    assert totals["total"] == 14500.0
    assert totals["iva_rate"] == pytest.approx(0.16)


def test_iva_exempt_from_reglas():
    session = {
        "reglas_economicas": {
            "tratamiento_iva": "Los servicios están exentos de IVA según artículo aplicable.",
        }
    }
    ctx = resolve_iva_context(session)
    assert ctx["iva_exempt"] is True
    assert ctx["iva_rate"] == 0.0


def test_attach_totals_to_canonical(monkeypatch):
    monkeypatch.setattr(
        "app.services.economic_calculation_service.economic_calc_on_capture_enabled",
        lambda: True,
    )
    out = attach_totals_to_canonical(
        {"items": [{"status": "captured", "amount_mxn": 1000.0}]},
        session_state={},
    )
    assert out["totals"]["subtotal"] == 1000.0
    assert out["totals"]["iva"] == 160.0
    assert out["totals"]["total"] == 1160.0
    assert out.get("totals_provenance_ui")


def test_build_price_capture_confirmation_includes_totals_table(monkeypatch):
    monkeypatch.setattr(
        "app.services.economic_calculation_service.economic_calc_on_capture_enabled",
        lambda: True,
    )
    state = {
        "session_line_items": [],
        "economic_user_inputs": {"price_zona_a": 45250.0},
        "capture_matrix_blocks": [
            {
                "matrix_rows": [
                    {"field": "price_zona_a", "label": "Zona A — tarifa mensual"},
                    {"field": "price_zona_b", "label": "Zona B — tarifa mensual"},
                ]
            }
        ],
        "pending_questions": [],
    }
    msg = build_price_capture_confirmation_message(
        session_state=state,
        label="Zona A — tarifa mensual",
        amount_mxn=45250.0,
        next_label="Zona B — tarifa mensual",
        missing_count=1,
    )
    assert "Quedó registrado" in msg
    assert "Totales actualizados" in msg
    assert "Subtotal" in msg
    assert "IVA" in msg
    assert "Zona B" in msg


def test_gate_generar_economica_blocks_when_incomplete():
    state = {
        "capture_matrix_blocks": [
            {
                "matrix_rows": [
                    {"field": "p1", "label": "Concepto 1"},
                    {"field": "p2", "label": "Concepto 2"},
                    {"field": "p3", "label": "Concepto 3"},
                    {"field": "p4", "label": "Concepto 4"},
                ]
            }
        ],
        "economic_user_inputs": {"p1": 100.0},
        "pending_questions": [],
        "session_line_items": [],
    }
    gate = gate_from_orch(state)
    assert gate.should_block is True
    assert "Precios pendientes" in gate.message or "faltan" in gate.message.lower()


def test_gate_generar_economica_allows_when_complete():
    state = {
        "capture_matrix_blocks": [
            {"matrix_rows": [{"field": "p1", "label": "Concepto 1"}]}
        ],
        "economic_user_inputs": {"p1": 100.0},
        "pending_questions": [],
        "session_line_items": [],
    }
    gate = gate_from_orch(state)
    assert gate.should_block is False
    assert gate.capture_complete is True


def test_flag_off_skips_totals_attachment(monkeypatch):
    from app.config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "ECONOMIC_CHAT_CALC_ON_CAPTURE", False)
    assert economic_calc_on_capture_enabled() is False
    out = attach_totals_to_canonical(
        {"items": [{"status": "captured", "amount_mxn": 100.0}]},
        session_state={},
    )
    assert "totals" not in out
