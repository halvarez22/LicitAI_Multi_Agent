from app.services.economic_cotization_filters import (
    is_required_price_source_artifact,
    is_contaminated_economic_pending_question,
    should_exclude_technical_for_cotization,
    should_remove_chatbot_intake_catalog_entry,
)


def test_exclude_hard_doc_even_with_service_words():
    req = {
        "id": "t-1",
        "descripcion": "Escrito bajo protesta de decir verdad para la prestación del servicio",
    }
    assert should_exclude_technical_for_cotization(req, set()) is True


def test_pending_question_detects_hard_doc_contamination():
    q = {
        "type": "economic_price",
        "label": "Precio de: Escrito bajo protesta de decir verdad",
    }
    assert is_contaminated_economic_pending_question(q) is True


def test_catalog_entry_documental_from_chatbot_is_removed():
    it = {
        "source": "chatbot_intake",
        "description": "Carta bajo protesta de decir verdad",
    }
    assert should_remove_chatbot_intake_catalog_entry(it) is True


def test_exclude_propuesta_tecnica_documental():
    req = {
        "id": "t-2",
        "descripcion": "Propuesta técnica describiendo especificaciones del servicio",
    }
    assert should_exclude_technical_for_cotization(req, set()) is True


def test_pending_question_detects_curp_documental():
    q = {
        "type": "economic_price",
        "label": "Precio (sin IVA): Impresión de la CURP.",
    }
    assert is_contaminated_economic_pending_question(q) is True


def test_exclude_programa_calendarizado_documental():
    req = {
        "id": "t-3",
        "descripcion": "Programa calendarizado de suministro de materiales y equipo",
    }
    assert should_exclude_technical_for_cotization(req, set()) is True


def test_detect_required_price_source_artifact():
    req = {
        "id": "t-4",
        "descripcion": "Catálogo de conceptos con cantidades y precios unitarios",
    }
    assert is_required_price_source_artifact(req) is True
