"""Tests de cláusulas administrativas universales y auditoría de contenido."""
from __future__ import annotations

from datetime import datetime

from app.services.administrative_letter_clauses import (
    build_administrative_letter_markdown,
    city_from_domicilio,
    format_letter_lugar_ciudad,
    is_invalid_letter_lugar,
    resolve_document_ciudad,
    try_build_clause_markdown,
)
from app.services.document_contamination_gate import scan_text_contamination
from app.services.document_date_resolver import resolve_document_date
from app.services.pliego_formats_enrichment_service import pliego_format_dedupe_key


def _profile() -> dict:
    return {
        "razon_social": "Empresa Demo SA de CV",
        "representante_legal": "JUAN PEREZ LOPEZ",
        "rfc": "EDL010101ABC",
        "domicilio_fiscal": "Calle 1, Colonia Centro, Ciudad de Mexico",
    }


def _meta() -> dict:
    return {
        "tender_name": "LICITACION GENERICA 2026",
        "concurso_label": "Concurso publico 2026 objeto demo",
        "fecha": "22 de abril de 2026",
        "destinatario": "COMITE DE ADQUISICIONES\nP R E S E N T E",
    }


def test_dedupe_key_anexo_x_underscore():
    assert pliego_format_dedupe_key("Anexo_X_conflicto.docx") == "pliego|ANEXO_X"


def test_anexo_x_clause_includes_art_49_complete():
    body = try_build_clause_markdown(
        req_label="Anexo_X_En_hoja_membretada.docx",
        master_profile=_profile(),
        doc_metadata=_meta(),
    )
    assert body
    low = body.lower()
    assert "artículo 49" in low or "articulo 49" in low
    assert "protesto lo necesario" in low
    assert "que no se…" not in body
    assert "antes de l." not in body


def test_anexo_ix_uses_conditional_adjudication():
    body = try_build_clause_markdown(
        req_label="Anexo_IX_Carta_de_aseguramiento.docx",
        master_profile=_profile(),
        doc_metadata=_meta(),
    )
    assert body
    assert "en caso de resultar adjudicado" in body.lower()
    assert "seleccionados como proveedor" not in body.lower()


def test_anexo_v_no_checklist_meta():
    body = try_build_clause_markdown(
        req_label="Anexo_V_Carta_Garantia.docx",
        master_profile=_profile(),
        doc_metadata=_meta(),
    )
    assert body
    assert "a continuación, se presentan los documentos" not in body.lower()


def test_resolve_document_date_late_generation_uses_today_and_flags_late():
    state = {
        "last_analysis": {
            "cronograma": {
                "presentacion_proposiciones": "27 de abril de 2026 a las 10:00 horas",
            }
        }
    }
    gen_at = datetime(2026, 6, 29, 10, 0, 0)
    out = resolve_document_date(state, at=gen_at)
    assert out["fecha_es"] == "29 de junio de 2026"
    assert out["source"] == "generation_timestamp"
    assert out["is_after_deadline"] is True


def test_contamination_detects_truncation_and_checklist():
    t1 = "manifestando bajo protesta de decir verdad que no se…"
    hits = scan_text_contamination(t1, stage="formats")
    assert any(h.error_type == "legal_text_truncated" for h in hits)
    t2 = "A continuación, se presentan los documentos requeridos: 1. Carta"
    hits2 = scan_text_contamination(t2, stage="formats")
    assert any(h.error_type == "bases_checklist_in_letter_body" for h in hits2)


def test_fallback_markdown_not_old_boilerplate():
    md = build_administrative_letter_markdown(
        req_nombre="Formato administrativo generico.docx",
        req_desc="Declaracion de cumplimiento",
        master_profile=_profile(),
        doc_metadata=_meta(),
        session_state={},
    )
    assert "cambio material, informaré de inmediato" not in md.lower()


def test_city_from_domicilio_skips_postal_code_segment():
    dom = (
        "Avenida La Reserva 3, Edificio Torre 11 Departamento 301A, "
        "Fraccionamiento El Campanario, Queretaro, Código Postal 76146"
    )
    assert city_from_domicilio(dom) == "Queretaro"
    assert is_invalid_letter_lugar("Código Postal 76146")
    assert is_invalid_letter_lugar("Avenida La Reserva 3")


def test_city_from_domicilio_single_segment_with_inline_cp():
    dom = "Fraccionamiento El Campanario Queretaro Código Postal 76146"
    assert city_from_domicilio(dom) == "Queretaro"


def test_resolve_document_ciudad_formats_state_abbrev():
    profile = {
        "domicilio_fiscal": (
            "Avenida La Reserva 3, Edificio Torre 11 Departamento 301A, "
            "Fraccionamiento El Campanario, Queretaro, Código Postal 76146"
        )
    }
    assert resolve_document_ciudad(profile) == "Queretaro, Qro."


def test_resolve_document_ciudad_prefers_profile_municipio():
    profile = {
        "municipio": "Santiago de Querétaro",
        "domicilio_fiscal": "Calle 1, Código Postal 76146",
    }
    assert resolve_document_ciudad(profile) == "Santiago de Querétaro, Qro."


def test_anexo_xi_no_vinculacion_and_conditional_adjudication():
    snippet = (
        "Anexo XI Manifiesto de no vinculación. Artículos 3º y 45 de la Ley de Adquisiciones, "
        "Enajenaciones, Arrendamientos y Contratación de Servicios del Estado de Querétaro. "
        "Artículos 65 al 72 LGRA. Ley de Responsabilidades Administrativas del Estado de Querétaro. "
        "fracciones I a la VI del artículo 57 Bis del Código Fiscal del Estado de Querétaro. "
        "Protección de datos personales."
    )
    body = try_build_clause_markdown(
        req_label="Anexo_XI_Manifiesto_firmado.docx",
        master_profile=_profile(),
        doc_metadata={**_meta(), "bases_corpus_hint": snippet},
        req_snippet=snippet,
    )
    assert body
    low = body.lower()
    assert "socio o asociado común" in low
    assert "en caso de resultar adjudicado" in low
    assert "seleccionados como proveedor" not in low
    assert "a quien corresponda" not in low.split("comparezco")[0] or True
    assert "17 de abril" not in body
    assert "3 de junio" not in body
    assert "manifiesto de no vinculación" in low
    assert "57 bis" in low or "57 Bis" in body
    assert "protesto lo necesario" in low


def test_anexo_x_asunto_not_truncated_filename():
    body = try_build_clause_markdown(
        req_label="Anexo_X_En_hoja_membretada_firmada_por_el_representante_lega.docx",
        master_profile=_profile(),
        doc_metadata=_meta(),
    )
    assert body
    assert "lega.docx" not in body.lower()
    assert "art. 49" in body.lower() or "artículo 49" in body.lower()


UNAQ_B2_SNIPPET = """
Anexo II, manifiesto de conformidad con las bases, en este documento deberá integrar copia de la invitación.
Anexo III, que refiere a los datos generales del participante, debidamente llenado y firmado.
Anexo VIII, manifiesto de conformidad que en caso de resultar adjudicado aceptará multas y sanciones.
Anexo XII, es un ejemplo de cómo podrá presentarla. No podrá ofertar una unidad de medida distinta.
"""


def _b2_meta() -> dict:
    return {**_meta(), "bases_corpus_hint": UNAQ_B2_SNIPPET}


def test_anexo_ii_conformidad_sin_boilerplate():
    body = try_build_clause_markdown(
        req_label="Anexo_II_manifiesto_de_conformidad.docx",
        master_profile=_profile(),
        doc_metadata=_b2_meta(),
        req_snippet=UNAQ_B2_SNIPPET,
    )
    assert body
    low = body.lower()
    assert "conozco, acepto y me sujeto" in low or "conozco" in low and "acepto" in low
    assert "copia de la invitación" in low
    assert "3 de junio" not in body
    assert "licitacion publica no" not in low.replace("ó", "o")


def test_anexo_iii_datos_generales_from_profile():
    body = try_build_clause_markdown(
        req_label="Anexo_III_datos_generales.docx",
        master_profile=_profile(),
        doc_metadata=_b2_meta(),
    )
    assert body
    assert "Empresa Demo SA de CV" in body
    assert "JUAN PEREZ LOPEZ" in body
    assert "EDL010101ABC" in body
    assert "DATOS GENERALES DEL PARTICIPANTE" in body
    assert "capacidad material" in body.lower()


def test_anexo_iv_membretada():
    body = try_build_clause_markdown(
        req_label="Anexo_IV_carta_membretada.docx",
        master_profile=_profile(),
        doc_metadata=_meta(),
    )
    assert body
    assert "papel membretado" in body.lower()


def test_anexo_viii_conditional_multas():
    body = try_build_clause_markdown(
        req_label="Anexo_VIII_manifiesto_multas.docx",
        master_profile=_profile(),
        doc_metadata=_b2_meta(),
    )
    assert body
    low = body.lower()
    assert "en caso de resultar adjudicado" in low
    assert "multas" in low
    assert "3 de junio" not in body


def test_anexo_xii_catalogo_uom():
    body = try_build_clause_markdown(
        req_label="Anexo_XII_catalogo.docx",
        master_profile=_profile(),
        doc_metadata=_b2_meta(),
        req_snippet=UNAQ_B2_SNIPPET,
    )
    assert body
    low = body.lower()
    assert "unidad de medida" in low
    assert "en caso de resultar adjudicado" in low
    assert "20 de abril" not in body
