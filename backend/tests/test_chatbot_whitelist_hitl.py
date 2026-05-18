"""Regresión: lista blanca RAG durante HITL (consultas al instrumento / reglas económicas)."""

from app.agents.chatbot_rag import ChatbotRAGAgent


def test_whitelist_bases_plus_iva():
    q = "¿Qué dicen las bases sobre el IVA en la propuesta económica?"
    assert ChatbotRAGAgent._bases_consult_whitelist_during_hitl(q) is True


def test_whitelist_donde_dice_precio():
    q = "¿Dónde dice el pliego si hay precio máximo para la oferta?"
    assert ChatbotRAGAgent._bases_consult_whitelist_during_hitl(q) is True


def test_whitelist_tope_sin_bases_explicita():
    q = "¿Hay tope de precio o tabulador que deba respetar?"
    assert ChatbotRAGAgent._bases_consult_whitelist_during_hitl(q) is True


def test_whitelist_not_short_query():
    assert ChatbotRAGAgent._bases_consult_whitelist_during_hitl("hola") is False


def test_whitelist_reject_generic_junta():
    q = "¿Cuándo es la junta de aclaraciones y qué documentos llevo?"
    assert ChatbotRAGAgent._bases_consult_whitelist_during_hitl(q) is False


def test_take_from_sources_ine_uploaded():
    q = "subí el ine a las fuentes ¿puedes tomar el dato de ahí?"
    assert ChatbotRAGAgent._detect_take_from_sources_intent(q) is True


def test_take_from_sources_reject_pliego_read():
    q = "¿puedes leer el pliego?"
    assert ChatbotRAGAgent._detect_take_from_sources_intent(q) is False


def test_take_from_sources_subido():
    q = "ya tengo el ine subido revísalo"
    assert ChatbotRAGAgent._detect_take_from_sources_intent(q) is True


def test_capture_escape_with_question_mark():
    # Pregunta con «?» que no dispare aclaración HITL (p. ej. «qué»+«concepto» manda a aclaración, no a escape RAG).
    q = b"\xc2\xbfHay plazo de entrega en d\xc3\xadas h\xc3\xa1biles?".decode("utf-8")
    assert ChatbotRAGAgent._detect_capture_escape_intent(q) is True


def test_capture_escape_with_explain_keyword():
    q = "explicame ese requisito por favor"
    assert ChatbotRAGAgent._detect_capture_escape_intent(q) is True
