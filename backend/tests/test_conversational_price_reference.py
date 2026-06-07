"""Referencia de precios «igual que zona B» (Ítem A.8)."""

from __future__ import annotations

import pytest

from app.services.conversational_price_normalizer import resolve_price_reference


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("igual que zona a lunes", 1200.0),
        ("mismo que zona b", 2500.0),
        ("como la zona c", 3000.0),
    ],
)
def test_resolve_price_reference(utterance: str, expected: float):
    inputs = {
        "Zona A | L-D": 1200.0,
        "Zona B | horario": 2500.0,
        "zona c material": 3000.0,
    }
    val, err, conf = resolve_price_reference(utterance, inputs)
    assert err is None, utterance
    assert float(val) == expected
    assert conf >= 0.9


def test_resolve_price_reference_missing():
    val, err, conf = resolve_price_reference("igual que zona z", {})
    assert val is None
    assert err
    assert conf == 0.0
