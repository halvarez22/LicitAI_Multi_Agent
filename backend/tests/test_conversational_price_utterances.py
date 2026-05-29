"""
Batería de utterances para normalización conversacional de precios (Ítem A).
"""

from __future__ import annotations

import pytest

from app.services.conversational_price_normalizer import normalize_conversational_price

_UTTERANCES_EXPECT_35529 = [
    "35529",
    "35,529",
    "$35,529.00",
    "35 mil 529",
    "son 35529 pesos",
    "MXN 35529",
    "precio 35529 sin iva",
]

_UTTERANCES_VARIOUS = [
    ("12500", 12500.0),
    ("12,500.50", 12500.5),
    ("1.5", 1.5),
    ("0", 0.0),
    ("veintinueve", 29.0),
    ("trece mil", 13000.0),
    ("$1,250,000", 1250000.0),
    ("8500", 8500.0),
    ("8 mil 500", 8500.0),
    ("dos mil", 2000.0),
    ("15000 pesos mxn", 15000.0),
    ("999.99", 999.99),
    ("1000000", 1000000.0),
    ("25 mil", 25000.0),
]


@pytest.mark.parametrize("utterance", _UTTERANCES_EXPECT_35529)
def test_utterances_normalize_to_35529(utterance: str):
    val, err, _conf = normalize_conversational_price(utterance)
    assert err is None, utterance
    assert float(val) == 35529.0


@pytest.mark.parametrize("utterance,expected", _UTTERANCES_VARIOUS)
def test_utterances_various(utterance: str, expected: float):
    val, err, _conf = normalize_conversational_price(utterance)
    assert err is None, utterance
    assert float(val) == expected


def test_utterance_batch_count():
    assert len(_UTTERANCES_EXPECT_35529) + len(_UTTERANCES_VARIOUS) >= 15
