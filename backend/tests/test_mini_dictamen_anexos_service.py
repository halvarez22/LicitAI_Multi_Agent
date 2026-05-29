from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.intake_planner import IntakePlannerAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.mini_dictamen_anexos_service import (
    build_and_persist_mini_dictamen,
    build_mini_dictamen_anexos,
    get_blocking_annex_rows_for_stage,
    resolve_clarification_ticket,
)


def _inventory_item(
    canonical_id: str,
    display_name: str,
    category: str,
    *,
    description: str = "",
) -> dict:
    return {
        "canonical_id": canonical_id,
        "display_name": display_name,
        "description": description,
        "category": category,
        "tier": "anchored",
        "status": "pending",
        "generator_hint": display_name,
    }


def test_mini_dictamen_detecta_anexo_oficial_no_publicado():
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item(
                    "anexo_tecnico_2026",
                    "Anexo Técnico 2026 Abril a Diciembre",
                    "technical",
                    description="Plantilla obligatoria citada en bases.",
                )
            ]
        }
    }

    out = build_mini_dictamen_anexos("s1", session_state, documents=[], catalog={"items": []}, coverage_report={"rows": []})
    row = out.items[0]
    assert row.required_by_bases is True
    assert row.official_template_expected is True
    assert row.source_status.value == "missing"
    assert row.delivery_action.value == "clarification_required"
    assert row.coverage_status.value == "blocked"
    assert row.clarification_candidate is True
    assert out.clarification_tickets


def test_mini_dictamen_marca_espejo_valido_y_cubierto():
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item(
                    "anexo_m_integridad",
                    "Anexo M Declaración de Integridad",
                    "legal_administrative",
                )
            ]
        }
    }
    catalog = {
        "items": [
            {
                "source_filename": "12. Anexo M (Declaración de Integridad).docx",
                "filename_key": "anexo m declaracion de integridad",
                "document_class": "plantilla_oferta",
                "accion_recomendada": "generar",
                "sobre_inferido": "administrativo",
            }
        ]
    }
    coverage = {
        "rows": [
            {
                "source_filename": "12. Anexo M (Declaración de Integridad).docx",
                "estado_cobertura": "generado",
                "archivo_entregado": "_compranet_validated/SobreComplementaria/12. Anexo M (Declaración de Integridad).docx",
                "match_method": "task_documento",
                "causa": "Materializado en la última corrida.",
            }
        ]
    }

    out = build_mini_dictamen_anexos("s2", session_state, documents=[], catalog=catalog, coverage_report=coverage)
    row = out.items[0]
    assert row.source_status.value == "valid"
    assert row.delivery_action.value == "mirror"
    assert row.coverage_status.value == "covered"
    assert row.clarification_candidate is False
    assert out.summary.coverage_covered >= 1


def test_mini_dictamen_constancia_visita_pasa_a_presentar_fisico_y_no_bloquea():
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item(
                    "constancia_visita",
                    "Constancia de Visita",
                    "technical",
                    description="Presentar la constancia de visita a las instalaciones.",
                )
            ]
        }
    }
    catalog = {
        "items": [
            {
                "source_filename": "7. Anexo F Constancia de Visitas.xlsx",
                "filename_key": "anexo f constancia de visitas",
                "document_class": "evidencia_visita",
                "accion_recomendada": "presentar_fisico",
                "sobre_inferido": "tecnico",
            }
        ]
    }
    coverage = {
        "rows": [
            {
                "source_filename": "7. Anexo F Constancia de Visitas.xlsx",
                "estado_cobertura": "presentar_fisico",
                "causa": "Original o constancia del licitante/terceros; el sistema no genera este tipo de evidencia.",
            }
        ]
    }

    out = build_mini_dictamen_anexos("s_visita", session_state, documents=[], catalog=catalog, coverage_report=coverage)
    row = out.items[0]
    assert row.source_status.value == "reference_only"
    assert row.delivery_action.value == "presentar_fisico"
    assert row.coverage_status.value == "pending"
    assert row.severity.value == "warn"
    assert row.clarification_candidate is False


def test_mini_dictamen_curriculum_inferido_puede_generarse_controlado():
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item(
                    "curriculum_empresarial",
                    "Currículum Empresarial",
                    "technical",
                    description="Presentar el currículum empresarial con relación de principales clientes.",
                )
            ]
        }
    }

    out = build_mini_dictamen_anexos("s_curriculum", session_state, documents=[], catalog={"items": []}, coverage_report={"rows": []})
    row = out.items[0]
    assert row.source_status.value == "missing"
    assert row.delivery_action.value == "generate_controlled"
    assert row.coverage_status.value == "pending"
    assert row.severity.value == "warn"
    assert row.clarification_candidate is False
    assert out.clarification_tickets == []


def test_mini_dictamen_anexo_tecnico_referencial_puede_generarse_controlado():
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item(
                    "anexo_tecnico",
                    "Anexo Técnico",
                    "technical",
                    description="Presentar el anexo técnico completo en hoja membretada, rubricado y firmado por el representante legal.",
                )
            ]
        }
    }
    catalog = {
        "items": [
            {
                "source_filename": "ANEXO TÉCNICO.pdf",
                "filename_key": "anexo tecnico",
                "document_class": "pliego_referencia",
                "accion_recomendada": "referencia",
                "sobre_inferido": "tecnico",
            }
        ]
    }

    out = build_mini_dictamen_anexos("s_anexo_tecnico", session_state, documents=[], catalog=catalog, coverage_report={"rows": []})
    row = out.items[0]
    assert row.source_status.value == "reference_only"
    assert row.delivery_action.value == "generate_controlled"
    assert row.coverage_status.value == "pending"
    assert row.severity.value == "warn"
    assert row.clarification_candidate is False


def test_mini_dictamen_integra_catalogo_y_coverage_por_source_doc_id():
    session_state = {
        "document_inventory": {
            "items": [
                _inventory_item(
                    "anexo_m_integridad",
                    "Anexo M Declaracion de Integridad",
                    "legal_administrative",
                )
            ]
        }
    }
    documents = [
        {
            "id": "doc-anexo-m",
            "content": {"filename": "12. Anexo M (Declaración de Integridad).docx"},
            "metadata": {},
        }
    ]
    catalog = {
        "items": [
            {
                "doc_id": "doc-anexo-m",
                "source_filename": "12. Anexo M (Declaración de Integridad).docx",
                "filename_key": "anexo m declaracion de integridad",
                "document_class": "plantilla_oferta",
                "accion_recomendada": "generar",
                "sobre_inferido": "administrativo",
            }
        ]
    }
    coverage = {
        "rows": [
            {
                "source_doc_id": "doc-anexo-m",
                "source_filename": "12. Anexo M (Declaración de Integridad).docx",
                "estado_cobertura": "generado",
                "archivo_entregado": "_compranet_validated/SobreComplementaria/12. Anexo M (Declaración de Integridad).docx",
                "match_method": "generated_source_doc_id",
                "materialization_route": "mirror",
                "mirror_mode": "copy_docx_filled",
            }
        ]
    }

    out = build_mini_dictamen_anexos(
        "s_lineage_md",
        session_state,
        documents=documents,
        catalog=catalog,
        coverage_report=coverage,
    )
    row = out.items[0]
    assert row.coverage_status.value == "covered"
    assert row.delivery_action.value == "mirror"
    assert row.coverage_match_method == "generated_source_doc_id"


@pytest.mark.asyncio
async def test_resolve_clarification_ticket_baja_bloqueo_por_override():
    store = {
        "s3": {
            "document_inventory": {
                "items": [
                    _inventory_item(
                        "anexo_tecnico_2026",
                        "Anexo Técnico 2026 Abril a Diciembre",
                        "technical",
                    )
                ]
            }
        }
    }

    class Mem:
        async def get_session(self, sid):
            return store.get(sid)

        async def get_documents(self, sid):
            return []

        async def save_session(self, sid, data):
            store[sid] = data
            return True

    mini = await build_and_persist_mini_dictamen(Mem(), "s3")
    ticket_id = mini.clarification_tickets[0].ticket_id
    ticket = await resolve_clarification_ticket(
        Mem(),
        "s3",
        ticket_id,
        status="waived",
        resolution_note="Se decide continuar con override auditado.",
    )
    assert ticket.status.value == "waived"
    refreshed = store["s3"]["mini_dictamen_anexos"]
    rows = refreshed.get("items") or []
    assert rows[0]["severity"] == "warn"
    assert rows[0]["coverage_status"] == "pending"


@pytest.mark.asyncio
async def test_intake_planner_incluye_tickets_del_mini_dictamen():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    agent = IntakePlannerAgent(MCPContextManager(mem))
    inp = AgentInput(
        session_id="sess_md_1",
        company_id="co1",
        company_data={
            "results": {},
            "session_state": {
                "pending_questions": [],
                "clarification_tickets": [
                    {
                        "ticket_id": "clar_anexo_tecnico",
                        "display_name": "Anexo Técnico 2026",
                        "status": "open",
                        "priority": "blocking",
                        "question": "Necesito aclarar con la convocante el Anexo Técnico 2026.",
                        "reason": "required_annex_not_published",
                    }
                ],
            },
        },
    )
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    qs = out.data.get("questions") or []
    assert any(q.get("field_target") == "clarification_tickets.clar_anexo_tecnico" for q in qs)
    assert out.data["summary"]["blocking_count"] >= 1


def test_stage_blocking_rows_filtra_por_categoria():
    session_state = {
        "mini_dictamen_anexos": {
            "items": [
                {
                    "canonical_id": "adm_1",
                    "display_name": "Anexo K",
                    "category": "administrativo",
                    "severity": "blocking",
                    "coverage_status": "blocked",
                },
                {
                    "canonical_id": "tec_1",
                    "display_name": "Anexo Técnico",
                    "category": "technical",
                    "severity": "blocking",
                    "coverage_status": "blocked",
                },
            ]
        }
    }
    technical = get_blocking_annex_rows_for_stage(session_state, "technical")
    formats = get_blocking_annex_rows_for_stage(session_state, "formats")
    assert len(technical) == 1
    assert technical[0]["canonical_id"] == "tec_1"
    assert len(formats) == 1
    assert formats[0]["canonical_id"] == "adm_1"
