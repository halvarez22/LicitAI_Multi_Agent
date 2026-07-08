"""Gate anti-contaminación de preguntas para junta de aclaraciones (HRU)."""
from __future__ import annotations

from app.services.junta_aclaraciones_questions_service import build_junta_aclaraciones_questions
from app.services.junta_bases_corpus import BasesCorpus, build_bases_corpus, find_certification_cluster_citation, find_experience_year_conflict
from app.services.junta_contamination_gate import passes_junta_question_gate

ISAPEG_BASES = """
Licitación pública nacional presencial 40004001-003-24 servicio de limpieza hospitalaria.
REQUISITOS DEL PARTICIPANTE
experiencia mínima comprobable será de 1 (un) año en servicios similares.
Anexo M Carta de Declaración de Integridad
NOM-031-ENER laboratorio acreditado EMA.
"""

FOCON_SNIPPET = """
ARTÍCULO 16 CONSTITUCIÓN FEDERAL DE LOS ESTADOS UNIDOS MEXICANOS
experiencia de 12 años en operario por turno IMSS-BIENESTAR
Número LA-07-H0M-007H0M001-N-24-2025
experiencia mínima de 3 años en servicios similares
"""


def test_experience_conflict_rejects_constitucion_ocr_noise():
    corpus = BasesCorpus(
        session_id="isapeg",
        segments=[("FOCON 04.pdf", FOCON_SNIPPET)],
        filenames=["FOCON 04.pdf"],
    )
    assert find_experience_year_conflict(corpus) is None


def test_experience_conflict_valid_dual_years_in_bases():
    text = (
        "experiencia mínima de 5 años en obras similares. "
        "Asimismo se requiere experiencia de al menos 2 años en mantenimiento."
    )
    corpus = BasesCorpus(
        session_id="s_dual",
        segments=[("bases_0001.pdf", text)],
        filenames=["bases_0001.pdf"],
    )
    conflict = find_experience_year_conflict(corpus)
    assert conflict is not None
    assert "5" in conflict[2] and "2" in conflict[2]


def test_junta_gate_rejects_few_shot_and_internal_gap():
    few_shot = (
        "Con respecto a la cláusula 4.2, página 18, apartado REQUISITOS DEL PARTICIPANTE, "
        "donde se exige al menos 12 años de experiencia y en el anexo técnico se mencionan 3 años, "
        "¿a cuál de estos dos plazos debemos apegarnos?"
    )
    assert not passes_junta_question_gate(few_shot, session_hint="isapeg_servicios_de_limpieza")
    internal = (
        "No se proporciona información sobre el perfil de la empresa; "
        "verificar si la empresa tiene experiencia en servicios similares."
    )
    assert not passes_junta_question_gate(
        internal,
        source_ref="gap_analysis[1]",
        session_hint="isapeg_servicios_de_limpieza",
    )


def test_junta_gate_rejects_cross_tender_snippet():
    corpus = build_bases_corpus(
        "isapeg",
        [
            {"content": {"filename": "bases_0001.pdf", "extracted_text": ISAPEG_BASES}},
            {"content": {"filename": "FOCON 04.pdf", "extracted_text": FOCON_SNIPPET}},
        ],
    )
    assert not passes_junta_question_gate(
        "¿Confirma la convocante el requisito de operario por turno IMSS-BIENESTAR?",
        corpus=corpus,
        session_hint="isapeg_servicios_de_limpieza",
    )


def test_certification_question_includes_bases_page_citation():
    text = (
        "REQUISITOS TÉCNICOS\n"
        "--- PÁGINA 12 ---\n"
        "El licitante deberá presentar constancia de laboratorio acreditado ante EMA.\n"
        "Cumplimiento NOM-031-ENER-2010 para equipos de eficiencia energética.\n"
        "--- PÁGINA 13 ---\n"
        "Otros requisitos administrativos.\n"
    )
    corpus = BasesCorpus(
        session_id="s_cert",
        segments=[("bases_0001.pdf", text)],
        filenames=["bases_0001.pdf"],
    )
    cite = find_certification_cluster_citation(corpus)
    assert cite is not None
    assert cite["pagina"] == "12"
    assert cite["archivo"] == "bases_0001.pdf"

    from app.services.junta_thematic_discovery import discover_thematic_questions

    items = discover_thematic_questions(corpus)
    cert = next(it for it in items if it.get("source_ref") == "thematic_certification_scope")
    assert "página 12" in cert["pregunta"].lower()
    assert cert.get("pagina") == "12"
    assert cert.get("archivo_fuente") == "bases_0001.pdf"
    assert cert["provenance_ui"]["citation_quality"] == "cita_completa"


def test_isapeg_mixed_corpus_filters_contaminated_junta_items():
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "preguntas_junta_aclaraciones": [
                                "Con respecto a la cláusula 4.2, página 18, apartado REQUISITOS DEL PARTICIPANTE, "
                                "donde se exige al menos 12 años de experiencia y en el anexo técnico se mencionan 3 años, "
                                "¿a cuál de estos dos plazos debemos apegarnos para acreditar experiencia?"
                            ],
                            "gap_analysis": [
                                {
                                    "requisito": "Experiencia en servicios similares",
                                    "estado_empresa": "FALTANTE",
                                    "sugerencia": (
                                        "No se proporciona información sobre el perfil de la empresa; "
                                        "verificar si la empresa tiene experiencia en servicios similares."
                                    ),
                                    "pagina": "18",
                                    "archivo_fuente": "bases_0001.pdf",
                                }
                            ],
                        }
                    }
                },
            }
        ],
        "_junta_session_documents": [
            {
                "content": {
                    "filename": "bases_0001.pdf",
                    "extracted_text": ISAPEG_BASES,
                }
            },
            {
                "content": {
                    "filename": "FOCON 04.pdf",
                    "extracted_text": FOCON_SNIPPET,
                }
            },
        ],
    }
    bundle = build_junta_aclaraciones_questions("isapeg_servicios_de_limpieza", state)
    joined = " ".join(it.pregunta.lower() for it in bundle.items)
    assert "12 años" not in joined and "12 anos" not in joined
    assert "no se proporciona información sobre el perfil" not in joined
    assert "constitución federal" not in joined
    assert "imss-bienestar" not in joined
    assert bundle.excluded_contamination >= 1
    assert bundle.contamination_gate_enabled is True
