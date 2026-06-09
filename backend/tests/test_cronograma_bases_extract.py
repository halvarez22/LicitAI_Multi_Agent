from app.services.cronograma_bases_extract import (
    cronograma_has_extracted_dates,
    extract_cronograma_from_bases_text,
    extract_cronograma_from_calendar_table,
    merge_cronograma_with_bases,
    parse_spanish_date_fragment,
)
from app.services.cronograma_enrichment_service import (
    cronograma_improved,
    enrich_cronograma_from_rag,
    is_placeholder_cronograma_value,
)


MAdera_SNIPPET = """
3.1 CALENDARIO DE ACTOS LICITATORIOS:
3.2 VISITA AL SITIO DE INSTALACION.
Se llevará a cabo el 26 de enero del 2026 a las 10:00a.m. partiendo de las oficinas del Departamento de Obras Públicas.
3.3 JUNTA DE ACLARACIONES:
Se llevará a cabo el 26 de enero del 2026 a las 16:00 horas. en la sala de Cabildo.
3.4 ACTO DE PRESENTACIÓN Y APERTURA DE PROPOSICIONES
Se llevará a cabo el 30 de enero del 2026 11:00 horas en la Sala de Cabildo.
"""


def test_is_placeholder_fecha_no_especificada():
    assert is_placeholder_cronograma_value("Fecha no especificada")


ISSSTE_TABLE_SNIPPET = """
Evento | Fecha y Hora | Lugar
Publicación de la Convocatoria | 04 de enero de 2024 | Diario Oficial de la Federación y CompraNet.
Visita a las Instalaciones | 11 de enero del 2024 a las 11:00 hrs. | Coordinación de Servicios Generales
Junta de Aclaración a las Bases | 12 de enero del 2024 a las 12:00 hrs. | Sistema Electrónico CompraNet.
Presentación y Apertura de Proposiciones, Técnicas y Económicas | 22 de enero del 2024 a las 11:00 hrs. | CompraNet
Fallo | 29 de enero del 2024 a las 11:00 hrs. | CompraNet
Firma del Contrato | 02 de febrero del 2024 a las 12:00 hrs. | Coordinación de Servicios Generales
"""

ISSSTE_TABLE_OCR_SNIPPET = """
Visita a las Instalaciones | 11 de enero del 2024
a las 11:00 hrs. | Coordinación de Servicios Generales
Junta de Aclaración a las
Bases | 12 de enero del 2024
a las 12:00 hrs. | Sistema Electrónico CompraNet.
"""


def test_extract_issste_calendar_table_with_ocr_line_breaks():
    out = extract_cronograma_from_calendar_table(ISSSTE_TABLE_OCR_SNIPPET)
    assert "11 de enero del 2024" in out["visita_instalaciones"]
    assert "11:00" in out["visita_instalaciones"]
    assert "12 de enero del 2024" in out["junta_aclaraciones"]


def test_extract_issste_calendar_table():
    out = extract_cronograma_from_calendar_table(ISSSTE_TABLE_SNIPPET)
    assert "04 de enero de 2024" in out["publicacion_convocatoria"]
    assert "11 de enero del 2024" in out["visita_instalaciones"]
    assert "12 de enero del 2024" in out["junta_aclaraciones"]
    assert "22 de enero del 2024" in out["presentacion_proposiciones"]
    assert "29 de enero del 2024" in out["fallo"]
    assert "02 de febrero del 2024" in out["firma_contrato"]


def test_extract_madera_style_bases():
    out = extract_cronograma_from_bases_text(MAdera_SNIPPET)
    assert "26 de enero del 2026" in out["visita_instalaciones"]
    assert "26 de enero del 2026" in out["junta_aclaraciones"]
    assert "30 de enero del 2026" in out["presentacion_proposiciones"]


def test_parse_spanish_date_slash_format():
    dt = parse_spanish_date_fragment("Presentación: 27/04/2026 10:00 hrs")
    assert dt is not None
    assert dt.day == 27 and dt.month == 4 and dt.year == 2026


def test_parse_spanish_date_del_anio():
    dt = parse_spanish_date_fragment(
        "Se llevará a cabo el 30 de enero del 2026 11:00 horas"
    )
    assert dt is not None
    assert dt.year == 2026 and dt.month == 1 and dt.day == 30


BARDA_GUANAJUATO_SNIPPET = """
VISITA AL SITIO NOVENA. - De la visita al sitio. - los participantes podrán realizar conjuntamente
con el servidor público que designe la convocante una visita al sitio donde se ejecutará la obra,
misma que será el día 10 de diciembre del año 2025, siendo el lugar de la cita en: en la Dirección
de Costos y Presupuestos a las 10:00 horas.
JUNTA DE ACLARACIONES Para tratar lo relacionado con el objeto del mismo procedimiento de adjudicación,
se convoca a todos los participantes para su desahogo el día 10 de diciembre del año 2025 a las 10:30 hrs
en la Dirección de Costos y Presupuestos.
fecha y hora para tal efecto: en la Dirección de Costos y Presupuestos.
El día 19 de diciembre del 2025, a las 9:30 horas.
El acto de fallo y adjudicación del contrato se dictará el día 26 de diciembre del 2025 a las 10:10 horas
en la Dirección de Costos y Presupuestos.
"""


def test_extract_barda_guanajuato_del_ano_y_presentacion():
    out = extract_cronograma_from_bases_text(BARDA_GUANAJUATO_SNIPPET)
    assert cronograma_has_extracted_dates(out, min_dates=4)
    assert "10 de diciembre del año 2025" in out["visita_instalaciones"]
    assert "10 de diciembre del año 2025" in out["junta_aclaraciones"]
    assert "19 de diciembre del 2025" in out["presentacion_proposiciones"]
    assert "26 de diciembre del 2025" in out["fallo"]


def test_cronograma_has_extracted_dates_rejects_empty():
    assert cronograma_has_extracted_dates({}) is False
    assert cronograma_has_extracted_dates({"fallo": "Fecha no especificada"}) is False
    assert cronograma_has_extracted_dates({"fallo": "26 de diciembre del 2025"}) is True


ISSSTE_NARRATIVE_JUNTA_FALSE_POSITIVE = """
Los bienes se asignarán por partida según lo acordado en la
Junta de Aclaraciones. Los licitantes deberán revisar el calendario.

--- PÁGINA 8 ---
Evento | Fecha y Hora | Lugar
Junta de Aclaración a las
Bases | 12 de enero del 2024
a las 12:00 hrs. | CompraNet
"""


def test_junta_table_ignores_narrative_false_positive():
    out = extract_cronograma_from_calendar_table(ISSSTE_NARRATIVE_JUNTA_FALSE_POSITIVE)
    assert "12 de enero del 2024" in out["junta_aclaraciones"]


def test_merge_table_overrides_wrong_analyst_dates():
    before = {
        "publicacion_convocatoria": "11 de enero de 2024",
        "visita_instalaciones": "Visita: 11 de enero de 2024",
        "junta_aclaraciones": "11 de enero de 2024",
        "presentacion_proposiciones": "29 de enero de 2024",
        "fallo": "Fecha no especificada",
        "firma_contrato": "2 de febrero de 2024",
    }
    after = merge_cronograma_with_bases(before, ISSSTE_TABLE_SNIPPET)
    assert "04 de enero de 2024" in after["publicacion_convocatoria"]
    assert "12 de enero del 2024" in after["junta_aclaraciones"]
    assert "22 de enero del 2024" in after["presentacion_proposiciones"]
    assert "29 de enero del 2024" in after["fallo"]


def test_merge_replaces_placeholders_only():
    before = {k: "Fecha no especificada" for k in (
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    )}
    after = merge_cronograma_with_bases(before, MAdera_SNIPPET)
    assert cronograma_improved(before, after)
    assert after["fallo"] == "Fecha no especificada"


def test_enrich_with_bases_text_madera():
    before = {k: "Fecha no especificada" for k in (
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    )}

    class EmptyVdb:
        def query_texts(self, session_id, query, n_results=8):
            return {"documents": []}

        def fetch_page_documents(self, session_id, src, pg):
            return []

    out = enrich_cronograma_from_rag(
        "sess_x", before, vector_db=EmptyVdb(), bases_text=MAdera_SNIPPET
    )
    assert "26 de enero del 2026" in out["junta_aclaraciones"]


UNAQ_TABLE_SNIPPET = """
| Evento |  |  | Fecha |  |  | Hora |
--- | --- | --- | --- | --- | --- | --- | --- | ---
Envío de Invitaciones |  |  | 17/04/2026 |  |  |  |  |
Visita al sitio |  |  | 20/04/2026 |  |  | 10:00 hrs |  |
Junta de Aclaraciones |  |  | 22/04/2026 |  |  | 10:00 hrs. |  |
Recepción de Propuestas Técnicas y Económicas y
Apertura de Propuestas Técnicas |  |  | 27/04/2026 |  |  | 10:00 hrs.
11:30 hrs. |  |
Emisión de Fallo |  |  |  |  |  |  |  |
"""

UNAQ_NARRATIVE_FALLO = """
celebrará el acto de fallo el día 27 de abril del 2026 en las oficinas del Departamento de Adquisiciones de UNAQ.
"""


def test_extract_unaq_evento_fecha_hora_table():
    out = extract_cronograma_from_calendar_table(UNAQ_TABLE_SNIPPET)
    assert "17/04/2026" in out["publicacion_convocatoria"]
    assert "20/04/2026" in out["visita_instalaciones"]
    assert "10:00" in out["visita_instalaciones"]
    assert "22/04/2026" in out["junta_aclaraciones"]
    assert "27/04/2026" in out["presentacion_proposiciones"]


def test_merge_unaq_overrides_analyst_2023_hallucination():
    analyst = {
        "publicacion_convocatoria": "Publicación de la convocatoria: 15 de marzo de 2023",
        "visita_instalaciones": "Visita a las instalaciones: 22 de marzo de 2023",
        "junta_aclaraciones": "Junta de aclaraciones: 29 de marzo de 2023",
        "presentacion_proposiciones": "Presentación de propuestas: 27 de abril de 2023",
        "fallo": "Fallo: 4 de mayo de 2023",
        "firma_contrato": "Firma del contrato: 11 de mayo de 2023",
    }
    blob = UNAQ_TABLE_SNIPPET + UNAQ_NARRATIVE_FALLO + (" 2026 " * 40)
    after = merge_cronograma_with_bases(analyst, blob)
    assert "2023" not in after["publicacion_convocatoria"]
    assert "17/04/2026" in after["publicacion_convocatoria"]
    assert "22/04/2026" in after["junta_aclaraciones"]
    assert "27/04/2026" in after["presentacion_proposiciones"]
    assert "27 de abril del 2026" in after["fallo"]
    assert "2023" not in after["fallo"]


def test_extract_fallo_acto_celebrara_narrative():
    from app.services.cronograma_bases_extract import extract_hito_from_bases_text

    blob = (
        "se dará a conocer a través de junta pública en la que se "
        "celebrará el acto de fallo el día 27 de abril del 2026 en las oficinas del Departamento."
    )
    out = extract_hito_from_bases_text("fallo", blob)
    assert out is not None
    assert "27 de abril del 2026" in out
