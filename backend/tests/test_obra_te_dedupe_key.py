"""Mapeo universal obra|T/E desde nombres de archivo y corpus."""
from __future__ import annotations

from app.services.administrative_letter_clauses import (
    resolve_document_ciudad,
    try_build_clause_markdown,
)
from app.services.pliego_formats_enrichment_service import (
    obra_te_dedupe_key,
    pliego_format_dedupe_key,
)


def test_anexo_t1_underscore_filename():
    assert pliego_format_dedupe_key("Anexo_T-1.docx") == "obra|T1"
    assert obra_te_dedupe_key("3. Anexo T-1") == "obra|T1"


def test_anexo_e5_materiales():
    assert pliego_format_dedupe_key("Anexo_E-5_Materiales.docx") == "obra|E5"


def test_modelo_contrato_maps_t3():
    assert pliego_format_dedupe_key(
        "Modelo_de_Contrato_utilizado_por_la_Dirección_General_de_Obr.docx"
    ) == "obra|T3"


def test_carta_compromiso_proposicion_maps_e1():
    assert pliego_format_dedupe_key("Carta-Compromiso_de_la_Proposición.docx") == "obra|E1"


def test_manifestacion_cumplimiento_not_t6_via_alias():
    key = pliego_format_dedupe_key(
        "Manifestación_de_Cumplimiento_de_Obligaciones_Contractuales.docx"
    )
    assert key == "obra|T6"


def test_anexo_ae_maps_e2():
    assert pliego_format_dedupe_key("01_ANEXO_AE_PROPUESTA_ECONOMICA.docx") == "obra|E2"
    assert pliego_format_dedupe_key("03_CARTA_COMPROMISO_PRECIOS.docx") == "obra|E2"


def test_obra_t1_tabular_clause_no_contamination():
    body = try_build_clause_markdown(
        req_label="Anexo_T-1.docx",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "fecha": "17 de diciembre de 2025",
        },
        req_snippet="ANEXO T-1 NOMBRE UBICACIÓN FÍSICA PROPIEDAD CANTIDAD",
    )
    assert body
    low = body.lower()
    assert "anexo t-1" in low
    assert "relación de maquinaria" in low
    assert "anexo t-2" not in low
    assert "contrato no." not in low
    assert "comparezco" not in low
    assert "| ---" in body or "| --- |" in body


def test_city_from_convocante_leon():
    from app.services.convocante_resolver import city_from_convocante_text

    lugar = city_from_convocante_text(
        "H. AYUNTAMIENTO DE LEÓN, GTO.\nDIRECCIÓN GENERAL DE OBRA PÚBLICA"
    )
    assert "LEÓN" in lugar.upper()
    assert "GTO" in lugar.upper()


def test_resolve_document_ciudad_prefers_convocante():
    meta = {"lugar_convocante": "León, GTO", "convocante": "H. Ayuntamiento de León, Gto."}
    profile = {"domicilio_fiscal": "Paseo de la Reforma 123, Ciudad de México, CDMX"}
    ciudad = resolve_document_ciudad(profile, profile["domicilio_fiscal"], letter_meta=meta)
    assert "León" in ciudad
    assert "CDMX" not in ciudad


def test_obra_t2_tabular_clause_no_contamination():
    body = try_build_clause_markdown(
        req_label="Relación_de_contratos_de_obras_vigentes.docx",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "fecha": "17 de diciembre de 2025",
        },
        req_snippet=(
            "ANEXO T-2 CONTRATANTE DOMICILIO Y TELEFONO DEL CONTRATANTE "
            "DESCRIPCIÓN DE LA OBRA IMPORTE DEL CONTRATO AVANCE FINANCIERO FECHA DE TERMINACION"
        ),
    )
    assert body
    low = body.lower()
    assert "anexo t-2" in low
    assert "relación de contratos" in low
    assert "contrato no." not in low
    assert "anexo t-1" not in low
    assert "comparezco" not in low
    assert "no se incluye" in low
    assert "contratante" in low


def test_obra_t3_pliego_contract_clause_extracts_from_corpus():
    from app.services.administrative_letter_clauses import (
        extract_obra_t3_contract_from_corpus,
        try_build_clause_markdown,
    )

    corpus = (
        "ANEXO T-3 MODELO DE CONTRATO (FIRMADO DE CONFORMIDAD) --- PÁGINA 8 --- "
        "Contrato para la ejecución de la obra pública a base de precios unitarios "
        "por tiempo determinado, que celebran por una parte el Municipio de León, Gto., "
        "representado en este acto por la Arquitecta LAURA ELENA BECERRA GARCÍA, "
        "en su carácter de Directora General de Obra Pública a quien en lo sucesivo se le "
        "denominará LA CONTRATANTE y por la otra, la Persona Moral: SOLUCIONES DIOR, "
        "S.A. DE C.V., representada en este acto por el ING. LUIS ERNESTO DIEZ DE SOLLANO "
        "TAPIA, en su carácter de representante legal a quien en adelante se le denominará "
        "EL CONTRATISTA al tenor de lo preceptuado en los artículos 1, 4, 9, 10, 14. "
        "D E C L A R A C I O N E S I.- DECLARA LA CONTRATANTE: A) Ser una Institución "
        "de Orden Público. " + ("Cláusula de ejemplo. " * 400)
        + " --- PÁGINA 39 --- ANEXO T-4 Bases y requisitos"
    )
    extracted = extract_obra_t3_contract_from_corpus(corpus)
    assert extracted
    assert "contrato para la ejecución" in extracted.lower()
    assert "declara" in extracted.lower()

    body = try_build_clause_markdown(
        req_label="Modelo_de_Contrato_utilizado.docx",
        master_profile={
            "razon_social": "CONSTRUCTORA INFRAESTRUCTURA NACIONAL, S.A. DE C.V.",
            "representante_legal": "Juan Carlos López Martínez",
            "rfc": "CIN2506089A3",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "bases_corpus_hint": corpus,
        },
    )
    assert body
    low = body.lower()
    assert "anexo t-3" in low
    assert "firmado de conformidad" in low
    assert "soluciones dior" not in low
    assert "constructora infraestructura nacional" in low
    assert "criterios de evaluación" not in low
    assert "comparezco" not in low
    assert "presente.-" not in low


def test_obra_t5_acta_attachment_no_false_attendance():
    corpus = (
        "JUNTA DE ACLARACIONES se convoca el día 10 de diciembre del año 2025 a las 10:30 hrs "
        "en la Dirección de Costos y Presupuestos. "
        "ANEXO T-5. Copia del acta correspondiente a la Visita del Sitio de los Trabajos "
        "y Junta de aclaraciones, expedida por un servidor público."
    )
    body = try_build_clause_markdown(
        req_label="Anexo_T-5_Acta_Visita_Junta.docx",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "bases_corpus_hint": corpus,
        },
    )
    assert body
    low = body.lower()
    assert "anexo t-5" in low
    assert "[consignar]" in low
    assert "comparezco" not in low
    assert "presente.-" not in low
    assert "manifiesto que asistí" not in low


def test_obra_t6_manifestacion_no_invented_contract_obligations():
    corpus = (
        "ANEXO T-6 Manifestación bajo protesta de decir verdad de encontrarse al corriente "
        "con el cumplimiento de sus obligaciones contractuales, fiscales y de previsión social. "
        "(En caso de asociación deberán presentar el escrito por cada uno de los asociados). "
        "ANEXO T-7 Manifestación de las partes de la obra que pretenda subcontratar"
    )
    body = try_build_clause_markdown(
        req_label="Manifestación_de_Cumplimiento_de_Obligaciones_Contractuales.docx",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "bases_corpus_hint": corpus,
        },
    )
    assert body
    low = body.lower()
    assert "anexo t-6" in low
    assert "al corriente" in low
    assert "previsión social" in low or "prevision social" in low
    assert "asociación" in low or "asociacion" in low
    assert "expediente técnico" not in low
    assert "cumplimiento ambiental" not in low
    assert "finiquito de la obra" not in low


def test_obra_t7_subcontratacion_no_false_t2_reference():
    corpus = (
        "ANEXO T-7 Manifestación de las partes de la obra que pretenda subcontratar "
        "ANEXO T-8 Aviso de privacidad"
    )
    body = try_build_clause_markdown(
        req_label="Manifestación_de_las_partes_de_la_obra_que_pretenda_subcontr.docx",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "bases_corpus_hint": corpus,
        },
    )
    assert body
    low = body.lower()
    assert "anexo t-7" in low
    assert "[consignar]" in low
    assert "anexo t-2" not in low
    assert "relación de contratos" not in low
    assert "| ---" in body or "[consignar]" in low


def test_obra_t4_pliego_bases_clause_extracts_from_corpus():
    from app.services.administrative_letter_clauses import extract_obra_t4_bases_from_corpus

    corpus = (
        "ANEXO T-4 BASES Y REQUISITOS --- PÁGINA 26 --- "
        "BASES Y REQUISITOS TIPO DE LICITACIÓN. Licitación Pública Nacional "
        "LICITACIÓN PÚBLICA NUM. D/080/2025 OBRA: CONSTRUCCIÓN DE BARDA. "
        "DISPOSICIONES GENERALES PRIMERA. - Las presentes Bases se sujetarán a la LOPSRM. "
        + ("SEGUNDA disposición normativa. " * 500)
        + " ANEXO T-5 Copia del acta de visita"
    )
    extracted = extract_obra_t4_bases_from_corpus(corpus)
    assert extracted
    assert "disposiciones generales" in extracted.lower()

    body = try_build_clause_markdown(
        req_label="Anexo_T-4_Bases_y_Requisitos_firmados.docx",
        master_profile={
            "razon_social": "Constructora Demo SA de CV",
            "representante_legal": "Juan Pérez",
            "rfc": "CDM010101CDM",
        },
        doc_metadata={
            "concurso_label": "Licitación Pública Num. D/080/2025",
            "bases_corpus_hint": corpus,
        },
    )
    assert body
    low = body.lower()
    assert "anexo t-4" in low
    assert "disposiciones generales" in low
    assert "comparezco" not in low
    assert "presente.-" not in low
    assert "criterios de evaluación" not in low
