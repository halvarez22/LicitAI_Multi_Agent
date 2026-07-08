"""Tests de mensajes UX humanos para gate de llenado documental."""
from app.services.document_fill_ux_messages import (
    build_fill_blocking_question,
    build_fill_quality_user_brief,
    build_fill_validation_event,
    humanize_field_key,
    human_line_for_issue,
    pick_fill_gate_pending_label,
)


def test_humanize_field_key_rfc():
    assert "RFC" in humanize_field_key("rfc")


def test_human_line_required_field_missing():
    line = human_line_for_issue(
        {
            "document_id": "propuesta_tecnica",
            "field_key": "rfc",
            "error_type": "required_field_missing",
        }
    )
    assert "RFC" in line or "rfc" in line.lower()
    assert "propuesta" in line.lower()


def test_build_fill_quality_user_brief_tarifa_mensual_formats():
    brief = build_fill_quality_user_brief(
        "formats",
        [{
            "document_id": "anexo_d_iii.docx",
            "field_key": "tarifa_mensual",
            "error_type": "placeholder_detected",
            "detected_value": "Tarifa mensual para horario: _______________",
        }],
        company_name="Manavil",
    )
    text = brief["full_message"].lower()
    assert "tarifa" in text or "precio" in text or "económica" in text or "economica" in text
    assert "propuesta econ" in text or "cotización" in text or "cotizacion" in text


def test_build_fill_quality_user_brief_no_jargon():
    brief = build_fill_quality_user_brief(
        "technical",
        [{"document_id": "doc1", "field_key": "rfc", "error_type": "required_field_missing"}],
        company_name="Empresa Demo",
    )
    text = brief["full_message"].lower()
    assert "chat_pricing" not in text
    assert "empresas" in text


def test_build_fill_quality_user_brief_clientes_con_experiencia_en_fuentes():
    summary = (
        "Ya tengo **curriculum.pdf** con referencias de **Organismo Demo**. "
        "Pulsa **Generar** otra vez."
    )
    brief = build_fill_quality_user_brief(
        "technical",
        [{
            "document_id": "02_TE-03_Propuesta.docx",
            "field_key": "content",
            "error_type": "placeholder_detected",
            "detected_value": "| 1 | [Domicilio del cliente 1] |",
        }],
        company_name="Empresa Demo S.A.",
        experience_summary=summary,
    )
    text = brief["full_message"]
    assert "curriculum.pdf" in text
    assert "Generar" in text
    assert "Empresa Demo" in text
    assert "Escríbeme aquí 1–3 clientes" not in text


def test_build_fill_blocking_question_is_actionable():
    q = build_fill_blocking_question(
        "technical",
        [{"document_id": "doc1", "field_key": "representante_legal", "error_type": "required_field_missing"}],
    )
    assert "representante" in q.lower()
    assert "escríbeme" in q.lower() or "escribeme" in q.lower()


def test_build_fill_validation_event_targets_companies_for_rfc():
    ev = build_fill_validation_event(
        {"document_id": "doc1", "field_key": "rfc", "error_type": "required_field_missing"},
        stage="technical",
    )
    assert ev["ux"]["primary_action"]["target"] == "companies"


def test_pick_fill_gate_label_no_pide_empresas_si_solo_plantilla():
    issues = [{
        "document_id": "anexo.docx",
        "field_key": "content",
        "error_type": "placeholder_detected",
        "detected_value": "Dato pendiente de confirmar por el representante legal.",
    }]
    assert pick_fill_gate_pending_label(issues) == "Revisar formatos con marcadores pendientes"
    brief = build_fill_quality_user_brief("formats", issues, company_name="Mayo y Torres")
    assert "ya se usaron" in brief["intro"].lower() or "ya se usaron" in brief["full_message"].lower()
    assert "ir a **empresas**" not in brief["next_steps"].lower()


def test_build_fill_validation_event_clientes_va_al_chat():
    ev = build_fill_validation_event(
        {
            "document_id": "TE-03.docx",
            "field_key": "content",
            "error_type": "placeholder_detected",
            "detected_value": "[Domicilio del cliente 1]",
        },
        stage="technical",
    )
    assert ev["ux"]["primary_action"]["target"] == "chat_pricing"


def test_chat_prompt_no_seguir_generando_si_falta_perfil():
    """Con RFC bloqueante + tarifa diferida, no prometer 'seguir generando'."""
    issues = [
        {
            "document_id": "profile",
            "field_key": "rfc",
            "error_type": "required_field_missing",
            "severity": "block",
        },
        {
            "document_id": "calculo_costos.xlsx",
            "field_key": "tarifa_mensual",
            "error_type": "required_field_missing",
            "expected_rule": "deferred_to_economic_stage",
            "severity": "warn",
        },
    ]
    brief = build_fill_quality_user_brief("formats", issues, company_name="Mayo y Torres")
    prompt = brief["chat_prompt"].lower()
    assert "seguir generando" not in prompt
    assert "empresas" in prompt or "rfc" in prompt
    assert "propuesta econ" in prompt or "económica" in prompt or "economica" in prompt

