from app.services.document_deliverable_filter import (
    filter_compliance_master_list,
    filter_consolidated_document_candidates,
    is_pliego_causal_or_prohibition,
    should_show_deliverable_in_ui,
)
from app.services.document_candidate_list_service import build_candidate_document_list


def test_is_pliego_causal_no_presentar_engrapado():
    assert is_pliego_causal_or_prohibition(
        "No presentar documentación engrapada o dentro de micas transparentes ni con broches"
    )
    assert is_pliego_causal_or_prohibition(
        "Datos contradictorios en la propuesta técnica y económica"
    )
    assert not is_pliego_causal_or_prohibition(
        "Carta de declaración de integridad", "Formato Anexo M"
    )


def test_build_candidate_list_excludes_causales_and_dedup():
    compliance = {
        "administrativo": [
            {
                "id": "AD-1",
                "nombre": "Acta constitutiva emitida por fedatario público",
                "descripcion": "Documento legal",
                "snippet": "Acta constitutiva",
                "tipo_accion": "presentar_fisico",
                "action_confidence": 0.9,
            },
            {
                "id": "AD-2",
                "nombre": "Acta constitutiva emitida por fedatario público o autoridad competente",
                "descripcion": "Duplicado",
                "snippet": "Acta constitutiva",
                "tipo_accion": "presentar_fisico",
                "action_confidence": 0.8,
            },
            {
                "id": "AD-146",
                "nombre": "No presentar documentación engrapada o dentro de micas transparentes",
                "descripcion": "Causal",
                "snippet": "No presentar documentación engrapada",
                "tipo_accion": "generar",
                "action_confidence": 0.95,
            },
        ],
        "tecnico": [],
        "formatos": [],
    }
    out = build_candidate_document_list(compliance, require_human_confirmation=False)
    names = [d["nombre"] for d in out["candidate_document_list"]]
    assert len(names) == 1, names
    assert "Acta constitutiva" in names[0]
    assert not any("engrapada" in n for n in names)


def test_should_show_rejects_causa_and_accepts_anexo_m():
    assert not should_show_deliverable_in_ui("Causa 1: No suministrar los bienes")
    assert not should_show_deliverable_in_ui("No presentar documentación engrapada")
    assert should_show_deliverable_in_ui("Anexo M Carta de Declaración de Integridad")
    assert should_show_deliverable_in_ui("Características de Muestras")
    assert should_show_deliverable_in_ui(
        "Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT",
        tipo_accion="presentar_fisico",
    )


def test_classify_acta_and_opinion_go_legal_not_economic():
    from app.services.compliance_consolidation_service import classify_deliverable_sobre

    assert classify_deliverable_sobre("Acta constitutiva notariada e inscrita") == "requisitos_legales"
    assert (
        classify_deliverable_sobre(
            "Opinión del Cumplimiento de Obligaciones Fiscales expedida por el SAT"
        )
        == "requisitos_legales"
    )
    assert classify_deliverable_sobre("Análisis de precios unitarios") == "sobre_2_economico"


def test_filter_consolidated_dedupes_acta_and_curriculum():
    raw = {
        "sobre_2_economico": [
            {"nombre_canonico": "Acta constitutiva em", "snippet_representativo": "x"},
            {
                "nombre_canonico": "Acta constitutiva emitida por fedatario público",
                "snippet_representativo": "x",
            },
        ],
        "sobre_1_tecnico": [
            {"nombre_canonico": "Curriculum Original", "snippet_representativo": "x"},
            {"nombre_canonico": "Curriculum de la empresa", "snippet_representativo": "x"},
        ],
        "requisitos_legales": [],
        "otros_requisitos_criticos": [],
        "_meta": {},
    }
    out = filter_consolidated_document_candidates(raw)
    assert len(out["requisitos_legales"]) == 1
    assert "acta" in out["requisitos_legales"][0]["nombre_canonico"].lower()
    assert len(out["sobre_1_tecnico"]) == 1


def test_filter_consolidated_strips_noise():
    raw = {
        "sobre_1_tecnico": [
            {"nombre_canonico": "Causa 1: No suministrar", "snippet_representativo": "x"},
            {"nombre_canonico": "Anexo M Carta de Declaración de Integridad", "snippet_representativo": "x"},
            {"nombre_canonico": "Junta de aclaraciones", "snippet_representativo": "x"},
        ],
        "sobre_2_economico": [],
        "requisitos_legales": [
            {"nombre_canonico": "Constancia de situación fiscal", "snippet_representativo": "x"},
        ],
        "otros_requisitos_criticos": [],
        "_meta": {"total_consolidados": 4},
    }
    out = filter_consolidated_document_candidates(raw)
    assert len(out["sobre_1_tecnico"]) == 1
    assert "Anexo M" in out["sobre_1_tecnico"][0]["nombre_canonico"]
    assert len(out["requisitos_legales"]) == 1
    assert out["_meta"]["total_consolidados"] == 2


def test_filter_compliance_master_list():
    raw = {
        "administrativo": [
            {"nombre": "Opinión SAT", "tipo_accion": "presentar_fisico"},
            {"nombre": "No presentar muestras requeridas", "tipo_accion": "generar"},
        ],
        "tecnico": [],
        "formatos": [],
    }
    filtered = filter_compliance_master_list(raw)
    assert len(filtered["administrativo"]) == 1
    assert filtered["administrativo"][0]["nombre"] == "Opinión SAT"
