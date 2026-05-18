from app.api.v1.routes.companies import (
    _apply_cif_constancia_patch,
    _apply_moral_representante_from_parser,
    _build_company_queries,
    _company_doc_title_suggests_cif,
    _extraction_quality,
    _is_llm_placeholder_profile_value,
    _looks_like_valid_corporate_name,
    _meta_priority,
    _merge_profile_with_hitl,
    _sanitize_llm_profile_placeholders,
)
from app.services.legal_representative_parser import resolve_rfc_persona_moral
from app.utils.ocr_quality import looks_like_low_signal_ocr


def test_extraction_quality_ok(monkeypatch):
    monkeypatch.setenv("COMPANY_OCR_MIN_CHARS", "10")
    monkeypatch.setenv("COMPANY_OCR_MIN_PAGES_WITH_TEXT", "1")
    ocr_ctx = {
        "extracted_text": "abcdefghij123",
        "pages": [{"page": 1, "text": "abcdefghij123"}],
    }
    quality = _extraction_quality(ocr_ctx)
    assert quality["ok"] is True
    assert quality["chars"] >= 10


def test_extraction_quality_low_text(monkeypatch):
    monkeypatch.setenv("COMPANY_OCR_MIN_CHARS", "50")
    monkeypatch.setenv("COMPANY_OCR_MIN_PAGES_WITH_TEXT", "1")
    ocr_ctx = {
        "extracted_text": "corto",
        "pages": [{"page": 1, "text": "corto"}],
    }
    quality = _extraction_quality(ocr_ctx)
    assert quality["ok"] is False


def test_extraction_quality_detects_low_signal_ocr(monkeypatch):
    monkeypatch.setenv("COMPANY_OCR_MIN_CHARS", "10")
    monkeypatch.setenv("COMPANY_OCR_MIN_PAGES_WITH_TEXT", "1")
    ocr_ctx = {
        "extracted_text": (
            "--- PÁGINA 1 ---\n000001\n--- PÁGINA 2 ---\n000002\n"
            "--- PÁGINA 3 ---\n000003\n--- PÁGINA 4 ---\n000004"
        ),
        "pages": [
            {"page": 1, "text": "000001"},
            {"page": 2, "text": "000002"},
            {"page": 3, "text": "000003"},
        ],
    }
    quality = _extraction_quality(ocr_ctx)
    assert quality["low_signal"] is True
    assert quality["ok"] is False


def test_looks_like_low_signal_ocr_detects_page_marker_noise():
    txt = "--- PÁGINA 1 ---\n000001\n--- PÁGINA 2 ---\n000002\n--- PÁGINA 3 ---\n000003"
    assert looks_like_low_signal_ocr(txt) is True


def test_looks_like_low_signal_ocr_repeated_pagina_tokens_still_low_signal():
    txt = (
        "--- PÁGINA 1 ---\n000001\n\n--- PÁGINA 2 ---\n000002\n\n--- PÁGINA 3 ---\n000003\n\n"
        "--- PÁGINA 4 ---\n000004\n\n--- PÁGINA 5 ---\n000005\n\n--- PÁGINA 6 ---\n000006"
    )
    assert looks_like_low_signal_ocr(txt) is True


def test_merge_profile_respects_manual_locked_fields():
    existing = {
        "representante_legal": "Nombre Manual Confirmado",
        "_manual_locked_fields": ["representante_legal"],
    }
    new = {"representante_legal": "Nombre Detectado OCR", "rfc": "ABC010101AA1"}
    merged = _merge_profile_with_hitl(existing, new)
    assert merged["representante_legal"] == "Nombre Manual Confirmado"
    assert merged["rfc"] == "ABC010101AA1"


def test_build_company_queries_for_moral():
    queries = _build_company_queries(is_fisica=False)
    assert any("representante legal" in q.lower() for q in queries)
    assert len(queries) >= 4
    assert any("domicilio" in q.lower() and "constancia" in q.lower() for q in queries)


def test_company_doc_title_suggests_cif():
    assert _company_doc_title_suggests_cif("CIF (SAT)") is True
    assert _company_doc_title_suggests_cif("Acta constitutiva") is False


def test_apply_cif_constancia_patch_llena_domicilio():
    profile = {"rfc": "ABC123456XYZ", "razon_social": "DEMO SA DE CV"}
    blob = (
        "Constancia de situación fiscal\n"
        "Domicilio fiscal\n"
        "Calle Falsa 123, Col. Ejemplo, CDMX, CP 01000\n"
        "Régimen General de Ley Personas Morales\n"
    )
    _apply_cif_constancia_patch(
        profile,
        blob,
        is_fisica=False,
        existing_profile={},
    )
    assert "01000" in profile["domicilio_fiscal"]


def test_meta_priority_prefers_asamblea_over_acta():
    acta = {"doc_type": "Acta Constitutiva"}
    asamblea = {"doc_type": "Asamblea Extraordinaria"}
    assert _meta_priority(asamblea) > _meta_priority(acta)


def test_meta_priority_prefers_acta_over_cif():
    acta = {"doc_type": "Acta Constitutiva"}
    cif = {"doc_type": "CIF (SAT)"}
    assert _meta_priority(acta) > _meta_priority(cif)


def test_is_llm_placeholder_detects_narrated_refusal():
    s = "No se especifica un nuevo representante legal en los documentos proporcionados."
    assert _is_llm_placeholder_profile_value(s) is True
    assert _is_llm_placeholder_profile_value("Juan Pérez López") is False


def test_merge_profile_skips_llm_placeholder_so_preserves_existing():
    existing = {
        "representante_legal": "Ana Gómez Torres",
        "objeto_social": "Comercialización de bienes.",
    }
    new = {
        "representante_legal": "No se especifica un nuevo representante legal en los documentos proporcionados.",
        "objeto_social": "No se especifica el objeto social en los documentos proporcionados.",
        "rfc": "CMT160107S83",
    }
    merged = _merge_profile_with_hitl(existing, new)
    assert merged["representante_legal"] == "Ana Gómez Torres"
    assert merged["objeto_social"] == "Comercialización de bienes."
    assert merged["rfc"] == "CMT160107S83"


def test_apply_moral_representante_parser_override_llm_cuando_trigger_fuerte():
    """El LLM no debe dejar apoderado viejo si el parser vio delegado especial / asamblea."""
    profile = {"representante_legal": "Pedro Gomez Soto"}
    parser = {
        "found": True,
        "representative": "Ana Ruiz Mendez",
        "trigger": "nombre_coma_caracter_delegado_especial",
    }
    _apply_moral_representante_from_parser(profile, parser, {})
    assert profile["representante_legal"] == "Ana Ruiz Mendez"


def test_apply_moral_representante_respeta_bloqueo_hitl():
    profile = {"representante_legal": "Nombre Confirmado Por Usuario"}
    parser = {
        "found": True,
        "representative": "Otro Nombre",
        "trigger": "nombre_coma_caracter_delegado_especial",
    }
    existing = {
        "representante_legal": "Nombre Confirmado Por Usuario",
        "_manual_locked_fields": ["representante_legal"],
    }
    _apply_moral_representante_from_parser(profile, parser, existing)
    assert profile["representante_legal"] == "Nombre Confirmado Por Usuario"


def test_sanitize_llm_profile_placeholders_normalizes_to_no_encontrado():
    profile = {
        "representante_legal": "No se especifica un nuevo representante legal en los documentos proporcionados.",
        "objeto_social": "Objeto claro resumido en una línea.",
    }
    _sanitize_llm_profile_placeholders(profile)
    assert profile["representante_legal"] == "No encontrado"
    assert profile["objeto_social"] == "Objeto claro resumido en una línea."


def test_corporate_name_rejects_ine_context_with_newlines():
    candidate = "NOMBRE:\nYUNUEN\nDOMICILIO:\nLEON\nAÑO DE REGISTRO 1992"
    assert _looks_like_valid_corporate_name(candidate) is False


def test_corporate_name_rejects_flattened_ine_context():
    candidate = "NOMBRE: YUNUEN DOMICILIO: LEON ANO DE REGISTRO 1992"
    assert _looks_like_valid_corporate_name(candidate) is False


def test_resolve_rfc_persona_moral_prefers_moral_over_representante_llm():
    ctx = (
        "RAZÓN SOCIAL: EJEMPLO SERVICIOS SA DE CV  RFC CMT160107S83  constancia de situación fiscal. "
        "Representante legal Juan Pérez con RFC TODE820602FR4."
    )
    out = resolve_rfc_persona_moral(ctx, "TODE820602FR4")
    assert out["value"] == "CMT160107S83"
    assert out["changed"] is True
    assert "deterministic" in out["strategy"]


def test_resolve_rfc_persona_moral_keeps_llm_when_moral_matches():
    ctx = "DENOMINACIÓN SOCIAL ACME RFC CMT160107S83 vigente."
    out = resolve_rfc_persona_moral(ctx, "CMT160107S83")
    assert out["value"] == "CMT160107S83"
    assert out["changed"] is False


def test_resolve_rfc_persona_moral_falls_back_when_only_fisica_in_text():
    ctx = "Apoderado RFC TODE820602FR4 para trámites."
    out = resolve_rfc_persona_moral(ctx, "TODE820602FR4")
    assert out["value"] == "TODE820602FR4"
    assert out["strategy"] == "llm_no_moral_rfc_pattern_in_text"
