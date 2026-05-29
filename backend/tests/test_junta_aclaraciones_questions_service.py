"""Tests del listado unificado para junta de aclaraciones."""

from app.services.junta_aclaraciones_questions_service import (
    CITATION_QUALITY_COMPLETE,
    CITATION_QUALITY_DOCUMENT_ONLY,
    CITATION_QUALITY_INSUFFICIENT,
    build_junta_aclaraciones_questions,
    bundle_needs_regeneration,
    format_junta_questions_plain_text,
    resolve_citation_quality,
)


def test_build_from_analyst_and_evidence_conflict():
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "preguntas_junta_aclaraciones": [
                                "¿Se aceptará experiencia en servicios similares de vigilancia?"
                            ],
                            "gap_analysis": [],
                            "alertas_descalificacion": [],
                        }
                    }
                },
            }
        ],
        "master_profile": {"anos_experiencia": 12},
        "evidence_profile": {
            "fields": {
                "anos_experiencia": {
                    "value": 3,
                    "source_doc": "CEDULA DE PUNTOS Y PORCENTAJES.pdf",
                    "confidence": 0.9,
                }
            }
        },
        "evidence_profile_overrides": {},
        "clarification_tickets": [
            {
                "ticket_id": "t1",
                "display_name": "Anexo III",
                "status": "ready_for_junta",
                "priority": "blocking",
                "question": "¿El formato debe llevar firma autógrafa en todas las hojas?",
                "reason": "template_ambiguous",
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("test_session", state)
    assert bundle.summary.total >= 2
    sources = {it.source.value for it in bundle.items}
    assert "analyst_junta" in sources
    assert "evidence_conflict" in sources
    assert "mini_dictamen" in sources
    eco_q = next(it for it in bundle.items if it.source_ref == "anos_experiencia")
    assert "12" in eco_q.pregunta or "3" in eco_q.pregunta
    assert "cuál" in eco_q.pregunta.lower()
    text = format_junta_questions_plain_text(bundle)
    assert "LISTADO DE PREGUNTAS" in text
    assert "convocante" in text.lower() or "?" in text


def test_experience_bases_vs_document_without_master_profile():
    state = {
        "evidence_profile": {
            "fields": {
                "anos_experiencia": {
                    "value": 3,
                    "source_doc": "CEDULA DE PUNTOS.pdf",
                    "snippet": "experiencia de: Máximo: 3 años",
                }
            }
        },
        "_junta_analysis_from_agent": {
            "audit_report": {},
            "requisitos_participacion": [
                {
                    "inciso": "13",
                    "pagina": "21",
                    "seccion": "REQUISITOS DEL PARTICIPANTE",
                    "texto_literal": "los años de experiencia acreditable deben ser al menos 12",
                    "archivo_fuente": "Bases.pdf",
                },
                {
                    "pagina": "52",
                    "seccion": "CV empresarial",
                    "texto_literal": "se deberá contar con al menos 3 años de experiencia en servicios similares",
                    "archivo_fuente": "Bases.pdf",
                },
            ],
        },
    }
    bundle = build_junta_aclaraciones_questions("s3", state)
    eco = [it for it in bundle.items if "experiencia" in it.pregunta.lower() or it.source_ref.startswith("anos")]
    assert eco
    assert "12" in eco[0].pregunta and "3" in eco[0].pregunta
    assert "REQUISITOS" in eco[0].pregunta or "página" in eco[0].pregunta


def test_filters_placeholder_analyst_questions():
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "preguntas_junta_aclaraciones": [
                                "Pregunta técnica para clarificar el punto X...",
                            ],
                            "gap_analysis": [
                                {
                                    "requisito": "...",
                                    "sugerencia": "...",
                                    "estado_empresa": "FALTANTE",
                                }
                            ],
                        }
                    }
                },
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("s4", state)
    assert bundle.summary.total == 1
    assert bundle.items[0].source_ref == "analyst_pending_citation_umbrella"
    assert bundle.items[0].provenance_ui.get("citation_quality") == CITATION_QUALITY_INSUFFICIENT


def test_legal_rfc_conflict_uses_canonical_dual_format():
    state = {
        "master_profile": {"rfc": "ABC123456XY1"},
        "evidence_profile": {
            "fields": {
                "rfc": {
                    "value": "XYZ987654AB2",
                    "source_doc": "Aclaraciones.pdf",
                    "snippet": "RFC del licitante: XYZ987654AB2",
                    "pagina": "8",
                }
            }
        },
        "_junta_analysis_from_agent": {
            "requisitos_participacion": [
                {
                    "inciso": "5",
                    "pagina": "12",
                    "seccion": "REQUISITOS DEL PARTICIPANTE",
                    "texto_literal": "El RFC del licitante deberá coincidir con el registrado ante el SAT",
                    "archivo_fuente": "Bases.pdf",
                },
            ],
        },
    }
    bundle = build_junta_aclaraciones_questions("s_rfc", state)
    legal = next(it for it in bundle.items if it.source_ref == "rfc")
    assert legal.pregunta.lower().startswith("con respecto")
    assert "establece que" in legal.pregunta.lower()
    assert "sin embargo" in legal.pregunta.lower() or "más adelante" in legal.pregunta.lower()
    assert "cuál de estos dos" in legal.pregunta.lower()


def test_gap_analysis_dual_format():
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "gap_analysis": [
                                {
                                    "requisito": "Se exige representante legal con poder notarial",
                                    "evidence_snippet": "Podrá comparecer el apoderado con carta poder simple",
                                    "pagina": "18",
                                    "archivo_fuente": "Bases.pdf",
                                    "seccion": "REQUISITOS DEL PARTICIPANTE",
                                    "estado_empresa": "AMBIGUO",
                                }
                            ],
                        }
                    }
                },
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("s_gap", state)
    assert bundle.summary.total == 1
    assert bundle.items[0].pregunta.lower().startswith("con respecto")
    assert "más adelante" in bundle.items[0].pregunta.lower()


def test_incomplete_bundle_triggers_regeneration():
    payload = {
        "schema_version": "1.1.0",
        "items": [
            {
                "pregunta": "Con respecto a el documento «Aclaraciones.pdf» y en el apartado documento de la convocatoria, donde se indica que X",
                "source_ref": "rfc_documento_sin_cita_bases",
            }
        ],
    }
    state = {
        "evidence_profile": {
            "fields": {
                "rfc": {"value": "EIN990622155", "source_doc": "Aclaraciones.pdf"},
                "representante_legal": {"value": "Juan", "source_doc": "Aclaraciones.pdf"},
                "anos_experiencia": {"value": 3, "source_doc": "CEDULA.pdf"},
            }
        },
        "_junta_analysis_from_agent": {
            "audit_report": {"preguntas_junta_aclaraciones": ["Pregunta técnica para clarificar el punto X..."]},
        },
    }
    assert bundle_needs_regeneration(payload, session_state=state) is True


def test_legacy_bundle_detected_for_regeneration():
    legacy = {
        "schema_version": "1.0.0",
        "items": [
            {
                "pregunta": (
                    "Solicitamos aclaración respecto al requisito de **RFC**. "
                    "En las bases y documentos de la convocatoria se observan criterios "
                    "que podrían interpretarse de forma distinta."
                )
            }
        ],
    }
    assert bundle_needs_regeneration(legacy) is True


def test_evidence_without_master_profile_canonical_format():
    state = {
        "evidence_profile": {
            "fields": {
                "rfc": {
                    "value": "XYZ987654AB2",
                    "source_doc": "Aclaraciones.pdf",
                    "snippet": "RFC del licitante: XYZ987654AB2",
                    "pagina": "8",
                }
            }
        },
        "_junta_analysis_from_agent": {
            "requisitos_participacion": [
                {
                    "inciso": "5",
                    "pagina": "12",
                    "seccion": "REQUISITOS DEL PARTICIPANTE",
                    "texto_literal": "El RFC del licitante deberá coincidir con EIN990622155",
                    "archivo_fuente": "Bases.pdf",
                },
            ],
        },
    }
    bundle = build_junta_aclaraciones_questions("s_ev", state)
    rfc_items = [it for it in bundle.items if "rfc" in it.source_ref]
    assert rfc_items
    assert rfc_items[0].pregunta.lower().startswith("con respecto")
    assert "establece que" in rfc_items[0].pregunta.lower()


def test_citation_quality_on_bundle_items():
    state = {
        "_junta_analysis_from_agent": {
            "requisitos_participacion": [
                {
                    "inciso": "13",
                    "pagina": "21",
                    "seccion": "REQUISITOS DEL PARTICIPANTE",
                    "texto_literal": "al menos 12 años de experiencia acreditable",
                    "archivo_fuente": "Bases.pdf",
                },
                {
                    "pagina": "52",
                    "seccion": "CV empresarial",
                    "texto_literal": "al menos 3 años de experiencia en servicios similares",
                    "archivo_fuente": "Bases.pdf",
                },
            ],
        },
        "evidence_profile": {
            "fields": {
                "anos_experiencia": {
                    "value": 3,
                    "source_doc": "CEDULA.pdf",
                    "snippet": "Máximo: 3 años",
                }
            }
        },
    }
    bundle = build_junta_aclaraciones_questions("s_cq", state)
    assert bundle.items
    assert bundle.items[0].provenance_ui.get("citation_quality") == CITATION_QUALITY_COMPLETE

    assert (
        resolve_citation_quality(
            pregunta="Con respecto al documento «Aclaraciones.pdf», donde se indica que X",
            pattern="documento_sin_cita_bases",
        )
        == CITATION_QUALITY_DOCUMENT_ONLY
    )
    assert (
        resolve_citation_quality(pregunta="Solicitamos aclaración respecto al requisito")
        == CITATION_QUALITY_INSUFFICIENT
    )


def test_ubicacion_documento_evita_de_en_el_apartado():
    from app.services.junta_aclaraciones_questions_service import (
        _build_junta_dual_question,
        _format_ubicacion_documento,
    )

    cita = {
        "archivo": "ANEXO TECNICO.pdf",
        "pagina": "29",
        "seccion": "REQUISITOS DEL PARTICIPANTE",
        "inciso": "b",
    }
    ubic = _format_ubicacion_documento(cita)
    assert "de en el apartado" not in ubic
    assert "documento «ANEXO TECNICO.pdf»" in ubic
    q = _build_junta_dual_question(
        cita,
        "texto requisito b",
        {**cita, "pagina": "30", "inciso": "e"},
        "texto requisito e",
        tema="domicilio fiscal del licitante",
    )
    assert "de en el apartado" not in q.lower()


def test_analyst_canonical_pregunta_marca_cita_completa():
    canonical = (
        "Con respecto a la cláusula 4.2, página 18, apartado REQUISITOS DEL PARTICIPANTE, "
        "donde se exige al menos 12 años de experiencia y en el anexo técnico se mencionan 3 años, "
        "¿a cuál de estos dos plazos debemos apegarnos para acreditar experiencia?"
    )
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "preguntas_junta_aclaraciones": [canonical],
                            "gap_analysis": [],
                            "alertas_descalificacion": [],
                        }
                    }
                },
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("s_canon", state)
    assert len(bundle.items) == 1
    assert bundle.items[0].provenance_ui.get("citation_quality") == CITATION_QUALITY_COMPLETE


def test_dedupe_similar_questions():
    state = {
        "tasks_completed": [
            {
                "task": "stage_completed:analysis",
                "result": {
                    "data": {
                        "audit_report": {
                            "preguntas_junta_aclaraciones": [
                                "¿Cuál es el plazo de entrega?",
                                "¿Cuál es el plazo de entrega?",
                            ],
                        }
                    }
                },
            }
        ],
    }
    bundle = build_junta_aclaraciones_questions("s2", state)
    assert bundle.summary.total == 1
