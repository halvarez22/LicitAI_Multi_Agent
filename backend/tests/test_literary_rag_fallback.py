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


def test_cronogram_noise_rejects_official_signature_without_act():
    s = (
        "Ciudad de México, 4 de diciembre de 2025 el H. Director de Obras Públicas "
        "Municipales del municipio."
    )
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_source_rejects_catalog_filename():
    assert not C._cronogram_literary_source_ok({"source": "catalogo_conceptos_licitante.pdf"})
    assert C._cronogram_literary_source_ok({"source": "BASES CONVOCATORIA 2025.pdf"})


def test_cronogram_predicate_accepts_junta_with_date():
    s = "La junta de aclaraciones se llevará el 10 de diciembre del año 2025 a las 10:30 hrs."
    assert C._cronogram_literary_predicate(s, s.lower())


def test_cronogram_caps_junta_title_not_noise():
    s = (
        "DE LA JUNTA DE ACLARACIONES Para tratar lo relacionado con el objeto del mismo "
        "procedimiento se convoca el día 10 de diciembre del año 2025 a las 10:30 hrs."
    )
    assert not C._is_cronogram_literary_noise_sentence(s)
    assert C._cronogram_literary_predicate(s, s.lower())


def test_cronogram_predicate_accepts_orphan_date_in_apertura_body():
    sent = "El día 19 de diciembre del 2025, a las 9:30 horas."
    body = (
        "Del acto de recepción y apertura de propuestas. Este acto se realizará "
        "en la Dirección de Costos. " + sent
    )
    assert C._cronogram_literary_predicate(sent, sent.lower(), body.lower())


def test_cronogram_noise_rejects_modification_clause():
    s = (
        "cualquier modificación a las bases de la licitación, derivada del resultado "
        "de la Visita al sitio o a la Junta de aclaraciones, será considerada como parte "
        "integrante de las propias bases de licitación."
    )
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_noise_rejects_legal_declaration_g():
    s = (
        "G) Que tiene pleno conocimiento de que con fecha 09 de octubre del 2024, "
        "se celebró entre el Municipio y el licitante un convenio."
    )
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_noise_rejects_caps_schedule_line():
    s = "10 DE DICIEMBRE DEL 2025 A LAS 10:30 HRS."
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_noise_rejects_signature_during_act():
    s = (
        "F) Durante el acto de presentación y apertura de propuestas los documentos "
        "denominados escrito de proposición (anexo E-1) deberán ser firmados por un servidor público."
    )
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_noise_rejects_cost_adjustment_clause():
    s = (
        "El procedimiento de ajuste de costos deberá pactarse en el contrato y se sujetará "
        "a la revisión y ajuste de los costos; la fecha de origen de los precios será la del acto."
    )
    assert C._is_cronogram_literary_noise_sentence(s)


def test_cronogram_source_rejects_convocatoria_page_one():
    assert not C._cronogram_literary_source_ok(
        {"source": "CONVOCATORIA OBRA 2025.pdf", "page": 1}
    )


def test_literary_sources_action_is_ui_navigate():
    actions = C._literary_sources_actions()
    assert actions[0]["action_kind"] == "ui"
    assert actions[0]["action_id"] == "OPEN_SOURCES_PANEL"


def test_short_source_label_bases():
    label = C._short_source_label(
        "202512091445410.D-080-2025 BASES PUBLICO TIPO B BARDA.pdf"
    )
    assert label == "Bases del procedimiento"


def test_resolve_primary_bases_doc_prefers_bases_over_convocatoria():
    sources = [
        "202512091445410 CONVOCATORIA TIPO B BARDA.pdf",
        "CATÁLOGO DE CONCEPTOS.pdf",
        "202512091445410 BASES PUBLICO TIPO B BARDA.pdf",
    ]
    assert C._resolve_primary_bases_doc(sources).endswith("BASES PUBLICO TIPO B BARDA.pdf")
