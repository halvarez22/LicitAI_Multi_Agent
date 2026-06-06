"""Regresión: calidad de preguntas de junta (corpus, gate, plantillas embebidas)."""

from app.services.junta_aclaraciones_questions_service import (
    build_junta_aclaraciones_questions,
    bundle_needs_regeneration,
)
from app.services.junta_bases_corpus import (
    build_bases_corpus,
    find_cross_jurisdiction_template_hints,
    template_embedded_in_bases,
)
from app.services.junta_citation_gate import (
    alert_item_supported,
    analyst_question_supported,
    is_analyst_few_shot_artifact,
)
from app.services.junta_thematic_discovery import discover_thematic_questions
from app.services.mini_dictamen_anexos_service import build_mini_dictamen_anexos


def _inventory_item(canonical_id: str, display_name: str) -> dict:
    return {
        "canonical_id": canonical_id,
        "display_name": display_name,
        "description": display_name,
        "category": "formatos",
        "tier": "anchored",
        "status": "pending",
        "generator_hint": display_name,
    }


def test_blocks_analyst_few_shot_without_corpus_support():
    toxic = (
        "Con respecto a la cláusula 4.2, página 18, apartado REQUISITOS DEL PARTICIPANTE, "
        "donde se exige al menos 12 años de experiencia y en el anexo técnico se mencionan 3 años, "
        "¿a cuál de estos dos plazos debemos apegarnos para acreditar experiencia?"
    )
    assert is_analyst_few_shot_artifact(toxic)
    corpus = build_bases_corpus(
        "s_gate",
        [
            {
                "content": {
                    "filename": "Bases.pdf",
                    "extracted_text": "experiencia mínima comprobable será de 1 año en obras similares.",
                }
            }
        ],
    )
    assert not analyst_question_supported(toxic, corpus, {})


def test_analyst_few_shot_filtered_from_junta_bundle():
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
                                    "requisito": "Experiencia mínima de 12 años",
                                    "estado_empresa": "FALTANTE",
                                    "evidence_snippet": "Fragmento idéntico al párrafo citado.",
                                    "pagina": "18",
                                    "archivo_fuente": "bases_convocatoria.pdf",
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
                    "filename": "Bases licitacion.pdf",
                    "extracted_text": (
                        "2.4 PROYECTO: se adjunta a las\n"
                        "experiencia mínima comprobable será de 1 (un) año.\n"
                        "FORMA AE-01 Carta compromiso de seriedad.\n"
                        "NOM-031-ENER laboratorio acreditado EMA.\n"
                    ),
                }
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("s_toxic", state)
    joined = " ".join(it.pregunta.lower() for it in bundle.items)
    assert "12 años" not in joined and "12 anos" not in joined
    assert not any("12" in it.pregunta and "3" in it.pregunta for it in bundle.items)
    thematic = [it for it in bundle.items if it.source.value == "thematic_bases"]
    assert thematic


def test_mini_dictamen_skips_missing_ticket_when_form_embedded_in_bases():
    bases = (
        "8.2 Carta compromiso (Forma AE-01).\n"
        "8.3 Proposición económica (Forma AE-02).\n"
        "FORMA AT-10 Relación de trabajos anteriores.\n"
    )
    documents = [{"content": {"filename": "Bases convocatoria.pdf", "extracted_text": bases}}]
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item("forma_ae_01", "Forma AE-01"),
                _inventory_item("forma_ae_02", "Forma AE-02"),
            ]
        }
    }
    out = build_mini_dictamen_anexos("s_emb", session_state, documents=documents, catalog={"items": []}, coverage_report={"rows": []})
    blocked = [it for it in out.items if it.clarification_candidate]
    assert len(blocked) == 0
    assert template_embedded_in_bases(build_bases_corpus("s_emb", documents), "Forma AE-01")


def test_groups_required_annex_not_published_tickets():
    tickets = [
        {
            "ticket_id": f"t{i}",
            "display_name": f"Forma AE-0{i}",
            "status": "ready_for_junta",
            "priority": "blocking",
            "reason": "required_annex_not_published",
        }
        for i in range(1, 5)
    ]
    state = {"clarification_tickets": tickets}
    bundle = build_junta_aclaraciones_questions("s_grp", state)
    grouped = [it for it in bundle.items if it.source_ref == "grouped_required_annex_not_published"]
    assert len(grouped) == 1
    assert "formatos" in grouped[0].pregunta.lower()


def test_bundle_schema_12_requires_regeneration():
    assert bundle_needs_regeneration({"schema_version": "1.1.1", "items": []}) is True


def test_cross_jurisdiction_template_hint_mazatlan_in_madera_bases():
    text = (
        "MUNICIPIO DE MADERA, CHIHUAHUA\n"
        "Convocatoria pública nacional.\n"
        "FORMA DD-05 Declaración general.\n"
        "El licitante bajo protesta...\n"
        "Mazatlán, Sinaloa, a_ de enero de 2013.\n"
    )
    corpus = build_bases_corpus(
        "s_cross",
        [{"content": {"filename": "Bases convocatoria.pdf", "extracted_text": text}}],
    )
    hints = find_cross_jurisdiction_template_hints(corpus)
    assert hints
    assert any(
        "mazatl" in str(h.get("foreign_city", "")).lower()
        and "sinaloa" in str(h.get("foreign_state", "")).lower()
        for h in hints
    )
    thematic = discover_thematic_questions(corpus)
    assert any(q.get("source_ref") == "thematic_cross_jurisdiction_template" for q in thematic)


def test_alert_rejected_when_only_partial_phrase_on_cited_page():
    """Palabras sueltas en otro contexto (p. ej. doc. falsa) no validan la cita."""
    page21 = (
        "1.3. Se verificará que las ofertas presentadas correspondan a las especificaciones.\n"
        "3. Se acreditite con la documentación idónea que la información o\n"
        "documentación proporcionada por los licitantes es falsa.\n"
    )
    corpus = build_bases_corpus(
        "s_partial",
        [
            {
                "content": {
                    "filename": "Bases licitacion.pdf",
                    "extracted_text": (
                        "MUNICIPIO DE MADERA, CHIHUAHUA\n"
                        "--- PÁGINA 21 ---\n"
                        f"{page21}"
                    ),
                }
            }
        ],
    )
    alert = {
        "motivo": "Falta de información o documentos que imposibiliten determinar su solvencia",
        "sugerencia": "Verificar la documentación proporcionada por los licitantes",
        "pagina": 21,
    }
    assert not alert_item_supported(alert, corpus)


def test_stale_analyst_alert_filtered_when_motivo_not_on_cited_page():
    page21 = (
        "1.1 Lista de documentos administrativos.\n"
        "1.2 Identificación oficial del representante.\n"
        "1.3 Comprobante de domicilio.\n"
    )
    corpus = build_bases_corpus(
        "s_alert",
        [
            {
                "content": {
                    "filename": "Bases licitacion.pdf",
                    "extracted_text": (
                        "MUNICIPIO DE MADERA, CHIHUAHUA\n"
                        "--- PÁGINA 21 ---\n"
                        f"{page21}"
                    ),
                }
            }
        ],
    )
    alert = {
        "motivo": "Falta de información o documentos que imposibiliten determinar su solvencia",
        "sugerencia": "Verificar la documentación proporcionada por los licitantes",
        "pagina": 21,
        "gravedad": "ALTA",
    }
    assert not alert_item_supported(alert, corpus)


def test_stale_alert_excluded_from_junta_bundle():
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "alertas_descalificacion": [
                                {
                                    "motivo": "Falta de información o documentos que imposibiliten determinar su solvencia",
                                    "sugerencia": "Verificar la documentación proporcionada por los licitantes",
                                    "pagina": 21,
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
                    "filename": "Bases licitacion.pdf",
                    "extracted_text": (
                        "MUNICIPIO DE MADERA, CHIHUAHUA\n"
                        "--- PÁGINA 21 ---\n"
                        "1.1 Lista de documentos.\n"
                        "1.2 Identificación.\n"
                    ),
                }
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("s_alert_bundle", state)
    joined = " ".join(it.pregunta.lower() for it in bundle.items)
    assert "verificar la documentación proporcionada" not in joined
