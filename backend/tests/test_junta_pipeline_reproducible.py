"""
Regresión: pipeline junta reproducible (corpus tipo bases + inventario, sin hardcode de sesión).
"""

from app.services.junta_aclaraciones_questions_service import (
    build_junta_aclaraciones_questions,
    is_internal_junta_item,
)
from app.services.mini_dictamen_anexos_service import build_mini_dictamen_anexos


def _bases_text_madera_like() -> str:
    return (
        "2.4 PROYECTO DE SUMINISTRO E INSTALACION: se adjunta a las\n"
        "8.2 Carta compromiso (Forma AE-01). 8.3 Proposición económica (Forma AE-02).\n"
        "FORMA AE-04 FORMA AE-08 FORMA AT-03 FORMA AT-10\n"
        "FORMATO DD 05 ejemplo Mazatlán LO-009\n"
        "experiencia mínima comprobable será de 1 (un) año en obras similares.\n"
        "NOM-031-ENER-2019 laboratorio acreditado EMA PAESE FIDE\n"
        "[Insertar número de licitación] [Nombre del Representante Legal]\n"
    )


def _inventory_item(cid: str, name: str, category: str = "economic") -> dict:
    return {
        "canonical_id": cid,
        "display_name": name,
        "description": name,
        "category": category,
        "tier": "anchored",
        "status": "pending",
        "generator_hint": name,
    }


def test_pipeline_produces_stable_convocante_set():
    documents = [
        {
            "content": {
                "filename": "Bases licitacion ejemplo.pdf",
                "extracted_text": _bases_text_madera_like(),
            }
        }
    ]
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item("anexo_9", "Anexo 9: Relación y Análisis de Costos del Suministro de Luminarias"),
                _inventory_item("forma_ae_01", "Forma AE-01"),
                _inventory_item("forma_ae_02", "Forma AE-02"),
                _inventory_item("forma_dd_05", "Forma DD05"),
            ]
        },
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
                                }
                            ],
                            "alertas_descalificacion": [
                                {
                                    "motivo": "Falta de información o documentos",
                                    "pagina": "21",
                                    "gravedad": "ALTA",
                                    "sugerencia": "Verificar documentación",
                                }
                            ],
                        }
                    }
                },
            }
        ],
    }

    mini = build_mini_dictamen_anexos(
        "sess_pipeline",
        session_state,
        documents=documents,
        catalog={"items": []},
        coverage_report={"rows": []},
    )
    blocked = [it for it in mini.items if it.clarification_candidate]
    assert len(blocked) <= 2

    session_state["clarification_tickets"] = [
        t.model_dump(mode="json") for t in mini.clarification_tickets
    ]
    bundle = build_junta_aclaraciones_questions(
        "sess_pipeline", session_state, documents=documents
    )

    assert bundle.schema_version == "1.2.0"
    assert bundle.summary.total >= 5
  # Sin artefacto 12/3
    joined = " ".join(it.pregunta for it in bundle.items)
    assert "12 años" not in joined and "12 anos" not in joined

    convocante = [it for it in bundle.items if not is_internal_junta_item(it)]
    assert bundle.summary.para_convocante == len(convocante)
    assert len(convocante) >= 5

    sources = {it.source.value for it in convocante}
    assert "thematic_bases" in sources
    assert "mini_dictamen" in sources

    thematic = [it for it in convocante if it.source.value == "thematic_bases"]
    assert len(thematic) >= 2

    mini_q = [it for it in convocante if it.source.value == "mini_dictamen"]
    assert len(mini_q) <= 2
