from app.services.conversation_normalizer import ConversationNormalizer


def test_normalize_capture_message_economic_price_has_structure():
    n = ConversationNormalizer()
    out = n.normalize_capture_message(
        field_label="Precio unitario por guardia antes de IVA",
        question="¿Cuál es el costo por guardia para este turno?",
        intent_type="economic_price",
        state_hint="first_item",
    )
    low = out.lower()
    assert "precio unitario por guardia" in low
    assert "responde solo con el número" in low
    assert "sin iva" in low
    assert "ejemplo" in low
    assert "en cuanto lo guardo" in low


def test_normalize_capture_message_strips_technical_terms():
    n = ConversationNormalizer()
    out = n.normalize_capture_message(
        field_label="validation_rule_1 blocking_issues",
        question="price_missing en economic_validation_blocking",
        intent_type="profile",
        state_hint="clarification",
    )
    low = out.lower()
    assert "blocking_issues" not in low
    assert "price_missing" not in low
    assert "economic_validation_blocking" not in low
    assert "validation_rule_" not in low


def test_normalize_saved_transition_follow_up_no_repeated_hola():
    n = ConversationNormalizer()
    out = n.normalize_saved_transition(
        saved_label="RFC",
        next_label="Domicilio Fiscal",
        next_question="Necesito tu domicilio fiscal completo.",
        next_intent_type="profile",
    )
    low = out.lower()
    assert "guardé rfc" in low or "guarde rfc" in low
    assert "seguimos con el siguiente" in low
    # En follow_up no debe volver a arrancar con saludo repetitivo.
    assert not low.startswith("hola")

