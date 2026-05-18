"""
test_go_no_go_agent.py — Pruebas unitarias y PBT de GoNoGoAgent.

Cubre el contrato de salida, schema_version, fallback sin compliance
y las propiedades 10 y 11 con hypothesis.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, settings
from hypothesis import strategies as st

from app.agents.go_no_go import GoNoGoAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_context():
    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": [
                {
                    "task": "stage_completed:compliance",
                    "result": {
                        "data": {
                            "summary": {"causas_desechamiento": []},
                            "administrativo": [],
                            "tecnico": [],
                            "formatos": [],
                        }
                    },
                }
            ]
        }
    })
    ctx.record_task_completion = AsyncMock(return_value=True)
    return ctx


@pytest.fixture
def agent(mock_context):
    return GoNoGoAgent(mock_context)


def _inp(session_id: str = "sess_test", master_profile: dict = None) -> AgentInput:
    return AgentInput(
        session_id=session_id,
        company_id="comp_1",
        company_data={"master_profile": master_profile or {}},
    )


# ---------------------------------------------------------------------------
# Pruebas unitarias obligatorias (Req. 8.1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_output_contract(agent):
    """AgentOutput válido con agent_id='go_no_go_001'."""
    resp = await agent.process(_inp())
    assert isinstance(resp, AgentOutput)
    assert resp.agent_id == "go_no_go_001"
    assert resp.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL, AgentStatus.ERROR)


@pytest.mark.asyncio
async def test_schema_version(agent):
    """GoNoGoResult.schema_version debe ser 1."""
    resp = await agent.process(_inp())
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data is not None
    assert resp.data.get("schema_version") == 1


@pytest.mark.asyncio
async def test_fallback_sin_compliance(mock_context):
    """Sin stage_completed:compliance en tasks_completed → status=PARTIAL."""
    mock_context.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": []  # Sin compliance
        }
    })
    agent = GoNoGoAgent(mock_context)
    resp = await agent.process(_inp())
    assert resp.status == AgentStatus.PARTIAL
    assert resp.agent_id == "go_no_go_001"


@pytest.mark.asyncio
async def test_semaforo_red_con_knockout(mock_context):
    """Con causas_desechamiento → semaforo=RED y requires_user_decision=True."""
    mock_context.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": [
                {
                    "task": "stage_completed:compliance",
                    "result": {
                        "data": {
                            "summary": {
                                "causas_desechamiento": [
                                    {"descripcion": "No presenta certificación ISO 9001"}
                                ]
                            },
                            "administrativo": [],
                            "tecnico": [],
                            "formatos": [],
                        }
                    },
                }
            ]
        }
    })
    agent = GoNoGoAgent(mock_context)
    resp = await agent.process(_inp())
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data["semaforo"] == "RED"
    assert resp.data["requires_user_decision"] is True
    assert resp.data["total_knockouts"] >= 1


@pytest.mark.asyncio
async def test_semaforo_green_sin_brechas(mock_context):
    """Sin brechas → semaforo=GREEN y requires_user_decision=False."""
    mock_context.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": [
                {
                    "task": "stage_completed:compliance",
                    "result": {
                        "data": {
                            "summary": {"causas_desechamiento": []},
                            "administrativo": [],
                            "tecnico": [],
                            "formatos": [],
                        }
                    },
                }
            ]
        }
    })
    agent = GoNoGoAgent(mock_context)
    resp = await agent.process(_inp(master_profile={"rfc": "ABC123", "capital_contable": "5000000"}))
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data["semaforo"] == "GREEN"
    assert resp.data["requires_user_decision"] is False


@pytest.mark.asyncio
async def test_error_en_detect_brechas_retorna_error(mock_context):
    """Si detect_brechas lanza excepción → status=ERROR sin propagar."""
    mock_context.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": [
                {"task": "stage_completed:compliance", "result": {"data": {}}}
            ]
        }
    })
    agent = GoNoGoAgent(mock_context)
    with patch("app.agents.go_no_go.detect_brechas", side_effect=RuntimeError("fallo interno")):
        resp = await agent.process(_inp())
    assert resp.status == AgentStatus.ERROR
    assert resp.agent_id == "go_no_go_001"


@pytest.mark.asyncio
async def test_score_tecnico_fallo_no_bloquea_agente(mock_context):
    """Si calculate_score_tecnico falla → agente retorna SUCCESS con score=None."""
    agent = GoNoGoAgent(mock_context)
    with patch("app.agents.go_no_go.calculate_score_tecnico", side_effect=RuntimeError("score error")):
        resp = await agent.process(_inp())
    assert resp.status == AgentStatus.SUCCESS
    assert resp.data.get("score_cumplimiento_tecnico") is None


# ---------------------------------------------------------------------------
# Property-based tests (Req. 8.1)
# ---------------------------------------------------------------------------

# Estrategia para compliance_data arbitrario
_compliance_st = st.fixed_dictionaries({
    "summary": st.fixed_dictionaries({
        "causas_desechamiento": st.lists(
            st.one_of(
                st.text(min_size=1, max_size=50),
                st.fixed_dictionaries({"descripcion": st.text(min_size=1, max_size=50)}),
            ),
            max_size=3,
        )
    }),
    "administrativo": st.lists(
        st.fixed_dictionaries({"descripcion": st.text(min_size=1, max_size=50)}), max_size=3
    ),
    "tecnico": st.lists(
        st.fixed_dictionaries({"descripcion": st.text(min_size=1, max_size=50)}), max_size=3
    ),
    "formatos": st.lists(
        st.fixed_dictionaries({"descripcion": st.text(min_size=1, max_size=50)}), max_size=3
    ),
})

_profile_st = st.dictionaries(
    keys=st.sampled_from(["rfc", "capital_contable", "anos_experiencia", "certificaciones"]),
    values=st.text(min_size=1, max_size=50),
    max_size=4,
)


@given(compliance_data=_compliance_st, master_profile=_profile_st)
@settings(max_examples=50)
def test_property_10_agent_output_valido(compliance_data, master_profile):
    """Propiedad 10: Para cualquier AgentInput válido, GoNoGoAgent.process retorna
    AgentOutput con agent_id='go_no_go_001' y status en {SUCCESS, PARTIAL, ERROR}.
    
    Valida: Requisito 5.1
    """
    import asyncio

    ctx = MagicMock(spec=MCPContextManager)
    ctx.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": [
                {
                    "task": "stage_completed:compliance",
                    "result": {"data": compliance_data},
                }
            ]
        }
    })
    ctx.record_task_completion = AsyncMock(return_value=True)

    agent = GoNoGoAgent(ctx)
    inp = AgentInput(
        session_id="prop10_sess",
        company_id="comp_prop10",
        company_data={"master_profile": master_profile},
    )

    resp = asyncio.get_event_loop().run_until_complete(agent.process(inp))

    assert isinstance(resp, AgentOutput)
    assert resp.agent_id == "go_no_go_001"
    assert resp.status in (AgentStatus.SUCCESS, AgentStatus.PARTIAL, AgentStatus.ERROR)


@given(compliance_data=_compliance_st, master_profile=_profile_st)
@settings(max_examples=50)
def test_property_11_schema_version_siempre_1(compliance_data, master_profile):
    """Propiedad 11: Todo GoNoGoResult producido tiene schema_version == 1.
    
    Valida: Requisito 6.3
    """
    import asyncio

    ctx = MagicMock(spec=MCPContextManager)
    ctx.get_global_context = AsyncMock(return_value={
        "session_state": {
            "tasks_completed": [
                {
                    "task": "stage_completed:compliance",
                    "result": {"data": compliance_data},
                }
            ]
        }
    })
    ctx.record_task_completion = AsyncMock(return_value=True)

    agent = GoNoGoAgent(ctx)
    inp = AgentInput(
        session_id="prop11_sess",
        company_id="comp_prop11",
        company_data={"master_profile": master_profile},
    )

    resp = asyncio.get_event_loop().run_until_complete(agent.process(inp))

    if resp.status == AgentStatus.SUCCESS and resp.data:
        assert resp.data.get("schema_version") == 1
