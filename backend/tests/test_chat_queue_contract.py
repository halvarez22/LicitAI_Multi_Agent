"""Contrato universal cola chat — anti-regresión paneles vs conversación."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.intake_planner import IntakePlannerAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.contracts.chat_queue_contract import (
    assert_chat_queue_compliant,
    filter_questions_for_chat,
    find_chat_queue_violations,
    is_panel_only_intake_item,
)
from app.services.hitl_queue_service import sanitize_chat_pending_questions


def _ctx():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    return MCPContextManager(mem)


@pytest.mark.parametrize(
    "qid,reason,expected_panel",
    [
        ("INTAKE-B-GNG-001", "brecha_detectada", True),
        ("INTAKE-B-CON-penalizaciones", "condicion_contractual", True),
        ("INTAKE-GAP-001", "gap_analysis", True),
        ("INTAKE-B-ECO-001", "solvencia_economica", False),
    ],
)
def test_panel_only_detection(qid, reason, expected_panel):
    q = {
        "question_id": qid,
        "provenance_ui": {"reason": reason},
        "question": "¿Confirmas?",
    }
    assert is_panel_only_intake_item(q) is expected_panel


def test_filter_questions_for_chat_strips_gng_and_con():
    raw = [
        {"question_id": "INTAKE-B-GNG-001", "question": "viabilidad", "provenance_ui": {"reason": "brecha_detectada"}},
        {"question_id": "INTAKE-B-CON-penalizaciones", "question": "penas", "provenance_ui": {"reason": "condicion_contractual"}},
        {
            "question_id": "INTAKE-B-ECO-001",
            "question": "¿Capital?",
            "field_target": "solvencia_economica.capital",
            "provenance_ui": {"reason": "solvencia_economica"},
        },
    ]
    filtered = filter_questions_for_chat(raw)
    assert len(filtered) == 1
    assert filtered[0]["question_id"] == "INTAKE-B-ECO-001"


@pytest.mark.asyncio
async def test_intake_planner_separa_panel_y_chat():
    agent = IntakePlannerAgent(_ctx())
    inp = AgentInput(
        session_id="sess_contract_1",
        company_id="co1",
        company_data={
            "results": {
                "analysis": {
                    "data": {
                        "requisitos_solvencia_economica": [
                            {"titulo": "Capital mínimo", "criticidad": "bloqueante", "confidence": 0.9}
                        ],
                        "condiciones_contractuales": {
                            "penalizaciones": "Multa del 10% por incumplimiento",
                        },
                        "audit_report": {
                            "gap_analysis": [
                                {
                                    "requisito": "ISO 9001",
                                    "estado_empresa": "FALTANTE",
                                    "gravedad": "ALTA",
                                    "accion_requerida": "Obtener certificado",
                                }
                            ]
                        },
                    }
                },
                "go_no_go": {
                    "data": {
                        "brechas": [{"descripcion": "Sin experiencia similar", "is_knockout": True}],
                    }
                },
            },
            "session_state": {"pending_questions": []},
        },
    )
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    qs = out.data.get("questions") or []
    vb = out.data.get("viability_brechas") or []
    cr = out.data.get("contractual_review") or []
    sg = out.data.get("strategic_gaps") or []

    assert any(x.get("question_id", "").startswith("INTAKE-B-GNG") for x in vb)
    assert any(x.get("question_id", "").startswith("INTAKE-B-CON") for x in cr)
    assert any(x.get("question_id", "").startswith("INTAKE-GAP") for x in sg)
    assert not any(str(x.get("question_id", "")).startswith("INTAKE-B-GNG") for x in qs)
    assert not any(str(x.get("question_id", "")).startswith("INTAKE-B-CON") for x in qs)
    assert not any(str(x.get("question_id", "")).startswith("INTAKE-GAP") for x in qs)

    chat_from_plan = filter_questions_for_chat(qs)
    assert_chat_queue_compliant(chat_from_plan)
    assert find_chat_queue_violations(sanitize_chat_pending_questions(chat_from_plan)) == []


@pytest.mark.asyncio
async def test_sanitize_cola_con_gng_legacy_vacia():
    legacy = [
        {
            "type": "intake_planner",
            "question_id": "INTAKE-B-GNG-001",
            "question": "¿Cómo resolver ISO?",
            "provenance_ui": {"reason": "brecha_detectada"},
        }
    ]
    assert sanitize_chat_pending_questions(legacy) == []
    assert_chat_queue_compliant([])
