"""Intención de corrección de precio en chat."""
from app.services.price_correction_chat import (
    detect_price_correction_intent,
    session_ready_for_price_correction,
)


def test_detect_natural_correction_without_number():
    out = detect_price_correction_intent(
        "el precio que te di esta mal y quiero corregirlo para regenerar nuestra propuesta economica"
    )
    assert out is not None
    assert out["needs_price"] is True
    assert out.get("new_value") is None


def test_detect_correction_with_amount():
    out = detect_price_correction_intent("Corrige el precio a 2,600,000")
    assert out is not None
    assert out["needs_price"] is False
    assert out["new_value"] == 2600000.0


def test_session_ready_with_mps():
    st = {"master_proposal_state": {"items": [{"partida": 1}], "total_base": 100.0}}
    assert session_ready_for_price_correction(st) is True
