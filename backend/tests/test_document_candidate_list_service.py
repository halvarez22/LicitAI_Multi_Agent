from app.services.document_candidate_list_service import build_candidate_document_list


def test_build_candidate_document_list_basic_summary():
    compliance = {
        "administrativo": [
            {
                "id": "AD-01",
                "nombre": "Acta constitutiva",
                "descripcion": "Documento legal de la empresa",
                "snippet": "Acta constitutiva de la empresa",
                "tipo_accion": "presentar_fisico",
                "action_confidence": 0.95,
            }
        ],
        "tecnico": [
            {
                "id": "TE-01",
                "nombre": "Propuesta técnica",
                "descripcion": "Documento a elaborar por el licitante",
                "snippet": "Presentar propuesta técnica firmada",
                "tipo_accion": "generar",
                "action_confidence": 0.9,
            }
        ],
        "formatos": [
            {
                "id": "FO-01",
                "nombre": "Anexo informativo",
                "descripcion": "Fecha del acto de apertura",
                "snippet": "La apertura será el 12 de mayo",
                "tipo_accion": "informativo",
                "action_confidence": 0.8,
            }
        ],
    }
    out = build_candidate_document_list(compliance, require_human_confirmation=False, low_conf_threshold=0.7)
    assert len(out["candidate_document_list"]) == 3
    assert out["candidate_summary"]["generar"] == 1
    assert out["candidate_summary"]["presentar_fisico"] == 1
    assert out["candidate_summary"]["informativo"] == 1
    assert out["candidate_summary"]["no_aplica"] == 0
    assert out["unresolved_count"] == 0
    assert out["needs_human_confirmation"] is False


def test_build_candidate_document_list_marks_unknown_and_no_aplica():
    compliance = {
        "administrativo": [],
        "tecnico": [
            {
                "id": "TE-07A",
                "nombre": "Anexo AT-07A",
                "descripcion": "No aplica para esta licitación",
                "snippet": "AT-07A NO APLICA",
                "tipo_accion": "unknown",
                "action_confidence": 0.92,
            }
        ],
        "formatos": [],
    }
    out = build_candidate_document_list(compliance, require_human_confirmation=True, low_conf_threshold=0.7)
    assert len(out["candidate_document_list"]) == 1
    item = out["candidate_document_list"][0]
    assert item["no_aplica"] is True
    assert item["tipo_accion_propuesto"] == "informativo"
    assert out["candidate_summary"]["no_aplica"] == 1
    assert out["unresolved_count"] == 1
    assert out["needs_human_confirmation"] is True


def test_build_candidate_document_list_filters_normative_noise():
    compliance = {
        "administrativo": [],
        "tecnico": [
            {
                "id": "TE-99",
                "nombre": "Normas de conducta",
                "descripcion": "Lineamientos generales para el acto de apertura",
                "snippet": "Los asistentes deberán guardar respeto durante la junta de aclaraciones",
                "tipo_accion": "informativo",
                "action_confidence": 0.91,
            }
        ],
        "formatos": [],
    }
    out = build_candidate_document_list(compliance, require_human_confirmation=False, low_conf_threshold=0.7)
    assert out["candidate_document_list"] == []
    assert out["candidate_summary"]["generar"] == 0
    assert out["candidate_summary"]["presentar_fisico"] == 0
    assert out["candidate_summary"]["informativo"] == 0


def test_build_candidate_document_list_keeps_annex_even_if_informative_wording():
    compliance = {
        "administrativo": [],
        "tecnico": [],
        "formatos": [
            {
                "id": "FO-12",
                "nombre": "Anexo XII",
                "descripcion": "Formato oficial de propuesta económica",
                "snippet": "Presentar Anexo XII debidamente requisitado y firmado",
                "tipo_accion": "generar",
                "action_confidence": 0.95,
            }
        ],
    }
    out = build_candidate_document_list(compliance, require_human_confirmation=False, low_conf_threshold=0.7)
    assert len(out["candidate_document_list"]) == 1
    assert out["candidate_document_list"][0]["nombre"] == "Anexo XII"
    assert out["candidate_summary"]["generar"] == 1
