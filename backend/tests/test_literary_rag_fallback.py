"""Citas literales RAG (qué dice / según bases) — sin LLM."""
from app.agents.chatbot_rag import ChatbotRAGAgent as C


def test_strip_chunk_source_prefix_removes_fuente_block():
    raw = (
        "[FUENTE: BASES.pdf | PÁGINA: 13] La garantía de cumplimiento al 10% "
        "del importe total contratado."
    )
    clean = C._strip_chunk_source_prefix(raw)
    assert "[FUENTE:" not in clean
    assert "10%" in clean
    assert ".pdf" not in clean


def test_support_evidence_detects_que_dice():
    assert C._detect_support_evidence_intent("que dice el anexo 1 sobre garantias")


def test_penalty_predicate_matches_pena_convencional():
    s = "La pena convencional por atraso será del 2% por semana."
    assert C._penalty_literary_predicate(s, s.lower())


def test_solvency_predicate_matches_sat():
    s = "Opinión del cumplimiento de obligaciones fiscales ante el SAT."
    assert C._solvency_literary_predicate(s, s.lower())


def test_solvency_noise_rejects_sua_plantilla():
    s = "Dicho personal deberá formar parte de la plantilla mediante copia del SUA y pago IMSS."
    assert C._is_solvency_literary_noise_sentence(s)
    assert not C._solvency_literary_predicate(s, s.lower())


def test_cronogram_noise_rejects_table_header():
    s = (
        "LICITACIÓN OBRA DESCRIPCIÓN INSCRIPCIONES VISITA AL SITIO "
        "JUNTA DE ACLARACIONES ACTO DE PRESENTACIÓN"
    )
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_predicate_accepts_junta_with_date():
    s = "La junta de aclaraciones se llevará el 10 de diciembre del año 2025 a las 10:30 hrs."
    assert C._cronogram_literary_predicate(s, s.lower())


def test_short_source_label_bases():
    label = C._short_source_label(
        "202512091445410.D-080-2025 BASES PUBLICO TIPO B BARDA.pdf"
    )
    assert label == "Bases del procedimiento"
