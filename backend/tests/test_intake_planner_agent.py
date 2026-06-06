from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.intake_planner import IntakePlannerAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus


def _ctx():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    return MCPContextManager(mem)


@pytest.mark.asyncio
async def test_intake_planner_prioriza_knockouts_primero():
    agent = IntakePlannerAgent(_ctx())
    inp = AgentInput(
        session_id="sess_intake_1",
        company_id="co1",
        company_data={
            "results": {
                "analysis": {
                    "data": {
                        "requisitos_solvencia_economica": [
                            {"titulo": "Capital mínimo requerido", "criticidad": "bloqueante", "confidence": 0.9}
                        ],
                        "requisitos_solvencia_legal": [{"titulo": "Padrón de proveedores", "confidence": 0.8}],
                    }
                },
                "go_no_go": {
                    "data": {
                        "brechas": [
                            {"descripcion": "No cumple certificación ISO", "is_knockout": True},
                            {"descripcion": "Falta contrato similar", "is_knockout": False},
                        ]
                    }
                },
            },
            "session_state": {"pending_questions": [{"field": "rfc", "question": "¿Cuál es tu RFC?"}]},
        },
    )
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    qs = out.data.get("questions") or []
    vb = out.data.get("viability_brechas") or []
    assert len(qs) >= 2
    assert vb[0]["priority"] == "BLOQUEANTE"
    assert out.data["summary"]["blocking_count"] >= 1


@pytest.mark.asyncio
async def test_intake_planner_deduplica_preguntas_parecidas():
    agent = IntakePlannerAgent(_ctx())
    inp = AgentInput(
        session_id="sess_intake_2",
        company_id="co1",
        company_data={
            "results": {
                "go_no_go": {
                    "data": {
                        "brechas": [
                            {"descripcion": "Falta padrón de proveedores", "field": "padron", "is_knockout": False},
                            {"descripcion": "Se requiere padrón de proveedores", "field": "padron", "is_knockout": False},
                        ]
                    }
                }
            },
            "session_state": {"pending_questions": []},
        },
    )
    out = await agent.process(inp)
    vb = out.data.get("viability_brechas") or []
    # Ambas brechas colapsan por field_target similar (panel Go/No-Go, no chat)
    assert len(vb) == 1
    assert len(out.data.get("questions") or []) == 0


@pytest.mark.asyncio
async def test_intake_planner_incluye_hints_de_quality_gate():
    agent = IntakePlannerAgent(_ctx())
    inp = AgentInput(
        session_id="sess_intake_qh_1",
        company_id="co1",
        company_data={
            "results": {},
            "session_state": {
                "pending_questions": [],
                "last_document_quality_waiting_hints": {
                    "reason": "Clasificación ambigua de anexos técnicos",
                    "metrics": {"total_items": 120, "unknown_count": 80},
                },
                "last_document_fill_quality_waiting_hints": {
                    "validation_passed": False,
                    "blocking_count": 2,
                    "warning_count": 1,
                    "metrics": {"issues_total": 3},
                },
            },
        },
    )
    out = await agent.process(inp)
    qs = out.data.get("questions") or []
    assert any(q.get("field_target") == "quality.classification.review" for q in qs)
    assert any(q.get("field_target") == "quality.fill.review" for q in qs)
    assert out.data["summary"]["blocking_count"] >= 1
