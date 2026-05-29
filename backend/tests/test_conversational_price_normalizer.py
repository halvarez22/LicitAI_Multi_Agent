from app.services.conversational_price_normalizer import normalize_conversational_price


def test_plain_number():
    val, err, conf = normalize_conversational_price("35529")
    assert err is None
    assert val == "35529"
    assert conf >= 0.9


def test_currency_and_commas():
    val, err, conf = normalize_conversational_price("$35,529.00")
    assert err is None
    assert float(val) == 35529.0


def test_mil_pattern():
    val, err, conf = normalize_conversational_price("35 mil 529")
    assert err is None
    assert float(val) == 35529.0


def test_spanish_words():
    val, err, conf = normalize_conversational_price("trece mil")
    assert err is None
    assert float(val) == 13000.0
    assert conf >= 0.85
