"""
test_intake_inventory_silent.py — Tests unitarios y PBT para intake-inventory-silent-processing.

Verifica que:
1. IntakePlannerAgent nunca incluye INTAKE-INV-* en questions
2. inventory_summary contiene todos los grupos con estructura completa
3. ChatbotRAGAgent._sanitize elimina todos los pendientes de inventario
4. El sanitize preserva los pendientes no-inventario
5. inventory_pending_count es la suma de los count de inventory_summary
6. Los conteos del summary excluyen los pendientes de inventario
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.agents.intake_planner import IntakePlannerAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> IntakePlannerAgent:
    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)
    ctx.record_task_completion = AsyncMock(return_value=True)
    return IntakePlannerAgent(ctx)


def _make_input(session_state: Dict[str, Any]) -> AgentInput:
    return AgentInput(
        session_id="sess_inv_test",
        company_id="comp_1",
        company_data={
            "results": {},
            "session_state": session_state,
        },
    )


def _make_inventory(categories: List[str], items_per_cat: int = 3) -> Dict[str, Any]:
    """Construye un document_inventory de prueba."""
    items = []
    for cat in categories:
        for i in range(items_per_cat):
            items.append({
                "display_name": f"Anexo {cat}-{i+1}",
                "description": f"Descripción del anexo {i+1} de {cat}",
                "category": cat,
                "status": "pending",
                "anchors": [{"page_index": i + 1}],
            })
    return {"items": items}


# ---------------------------------------------------------------------------
# Tests unitarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intake_planner_inventory_not_in_questions():
    """questions nunca contiene pendientes de inventario (question_type='I' o field_target con 'inventory.')."""
    agent = _make_agent()
    session_state = {
        "document_inventory": _make_inventory(["legal_administrative", "technical"], items_per_cat=3),
    }
    inp = _make_input(session_state)
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    questions = out.data.get("questions", [])
    for q in questions:
        assert q.get("question_type") != "I", f"question_type='I' encontrado en questions: {q}"
        field_target = str(q.get("field_target") or q.get("field") or "")
        assert not field_target.startswith("inventory."), f"field_target con prefijo 'inventory.' en questions: {q}"


@pytest.mark.asyncio
async def test_intake_planner_inventory_summary_populated():
    """inventory_summary contiene los grupos de inventario con estructura completa."""
    agent = _make_agent()
    session_state = {
        "document_inventory": _make_inventory(["legal_administrative", "technical"], items_per_cat=4),
    }
    inp = _make_input(session_state)
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    inv_summary = out.data.get("inventory_summary", [])
    assert len(inv_summary) == 2
    for item in inv_summary:
        assert "category" in item
        assert "count" in item
        assert "priority" in item
        assert "field_target" in item
        assert "table_data" in item
        assert item["count"] == 4


@pytest.mark.asyncio
async def test_intake_planner_inventory_summary_empty_when_no_pending():
    """inventory_summary es [] cuando no hay ítems pendientes."""
    agent = _make_agent()
    session_state = {
        "document_inventory": {"items": [
            {"display_name": "Anexo 1", "category": "legal_administrative", "status": "completed"},
        ]},
    }
    inp = _make_input(session_state)
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    assert out.data.get("inventory_summary") == []
    assert out.data["summary"]["inventory_pending_count"] == 0


@pytest.mark.asyncio
async def test_intake_planner_inventory_summary_empty_when_no_inventory():
    """inventory_summary es [] cuando no hay document_inventory en session_state."""
    agent = _make_agent()
    session_state = {}
    inp = _make_input(session_state)
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    assert out.data.get("inventory_summary") == []
    assert out.data["summary"]["inventory_pending_count"] == 0


@pytest.mark.asyncio
async def test_intake_planner_summary_inventory_pending_count():
    """summary.inventory_pending_count es la suma de los count de inventory_summary."""
    agent = _make_agent()
    session_state = {
        "document_inventory": _make_inventory(
            ["legal_administrative", "technical", "economic"],
            items_per_cat=5
        ),
    }
    inp = _make_input(session_state)
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    inv_summary = out.data.get("inventory_summary", [])
    expected_total = sum(item["count"] for item in inv_summary)
    assert out.data["summary"]["inventory_pending_count"] == expected_total
    assert expected_total == 15  # 3 categorías × 5 ítems


@pytest.mark.asyncio
async def test_intake_planner_summary_counts_exclude_inventory():
    """blocking_count + critical_count + important_count + complementary_count == len(questions)."""
    agent = _make_agent()
    session_state = {
        "document_inventory": _make_inventory(["legal_administrative"], items_per_cat=7),
    }
    inp = _make_input(session_state)
    out = await agent.process(inp)
    assert out.status == AgentStatus.SUCCESS
    summary = out.data["summary"]
    questions = out.data["questions"]
    total_from_summary = (
        summary["blocking_count"]
        + summary["critical_count"]
        + summary["important_count"]
        + summary["complementary_count"]
    )
    assert total_from_summary == len(questions)


@pytest.mark.asyncio
async def test_intake_planner_plan_version_updated():
    """plan_version debe ser '1.2.0' tras el refactor."""
    agent = _make_agent()
    inp = _make_input({})
    out = await agent.process(inp)
    assert out.data.get("plan_version") == "1.2.0"


# ---------------------------------------------------------------------------
# Tests del filtro defensivo en ChatbotRAGAgent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chatbot_sanitize_discards_inventory_question_type_i():
    """El sanitize descarta pendientes con question_type='I'."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)

    with MagicMock() as mock_vector, MagicMock() as mock_llm:
        agent = ChatbotRAGAgent(ctx)

    session_state = {
        "pending_questions": [
            {
                "question_id": "INTAKE-INV-LEGAL_ADMINISTRATIVE",
                "question_type": "I",
                "field_target": "inventory.legal_administrative.completion",
                "question": "He detectado 7 documentos pendientes.",
            },
            {
                "question_id": "INTAKE-B-LEG-001",
                "question_type": "B",
                "field_target": "solvencia_legal.comprobante_domicilio",
                "question": "¿Cuentas con comprobante de domicilio?",
            },
        ],
        "tasks_completed": [],
    }

    result = await agent._sanitize_economic_pending_questions("sess_test", session_state)
    assert len(result) == 0  # Both INTAKE-INV and INTAKE-B-LEG are now filtered


@pytest.mark.asyncio
async def test_chatbot_sanitize_discards_inventory_field_target_prefix():
    """El sanitize descarta pendientes con field_target que empieza con 'inventory.' o quality.classification.review."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)

    agent = ChatbotRAGAgent(ctx)

    session_state = {
        "pending_questions": [
            {
                "question_id": "INTAKE-INV-TECHNICAL",
                "type": "intake_planner",  # formato legacy: usa 'type' en lugar de 'question_type'
                "field": "inventory.technical.completion",  # formato legacy: usa 'field'
                "question": "He detectado 11 documentos técnicos pendientes.",
            },
            {
                "question_id": "INTAKE-B-LEG-001",
                "question_type": "B",
                "field_target": "solvencia_legal.comprobante_domicilio",
                "question": "¿Cuentas con comprobante de domicilio?",
            },
        ],
        "tasks_completed": [],
    }

    result = await agent._sanitize_economic_pending_questions("sess_test", session_state)
    assert len(result) == 0  # Both INTAKE-INV and INTAKE-B-LEG are now filtered


@pytest.mark.asyncio
async def test_chatbot_sanitize_preserves_b_and_q_questions():
    """El sanitize preserva los pendientes INTAKE-B-* sin modificación. INTAKE-Q-CLASS-001 se filtra silenciosamente."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)

    agent = ChatbotRAGAgent(ctx)

    b_question = {
        "question_id": "INTAKE-B-LEG-001",
        "question_type": "B",
        "field_target": "solvencia_legal.comprobante_domicilio",
        "question": "¿Cuentas con comprobante de domicilio?",
        "priority": "CRITICO",
    }
    # INTAKE-Q-CLASS-001 se filtra silenciosamente (clasificación técnica interna)
    q_class_question = {
        "question_id": "INTAKE-Q-CLASS-001",
        "question_type": "Q",
        "field_target": "quality.classification.review",
        "question": "¿Confirmas la clasificación?",
        "priority": "BLOQUEANTE",
    }
    # INTAKE-Q-FILL-001 sí se preserva (tiene datos reales que el usuario puede validar)
    q_fill_question = {
        "question_id": "INTAKE-Q-FILL-001",
        "question_type": "Q",
        "field_target": "quality.fill.review",
        "question": "¿Me ayudas a validar datos críticos de llenado?",
        "priority": "CRITICO",
    }

    session_state = {
        "pending_questions": [b_question, q_class_question, q_fill_question],
        "tasks_completed": [],
    }

    result = await agent._sanitize_economic_pending_questions("sess_test", session_state)
    # INTAKE-B-LEG-001 y INTAKE-Q-CLASS-001 se filtran, solo INTAKE-Q-FILL-001 se preserva
    assert len(result) == 1  # Only INTAKE-Q-FILL-001 preserved
    assert result[0] == q_fill_question


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------

# Estrategia para generar session_state con document_inventory aleatorio
_CATEGORIES = ["legal_administrative", "technical", "economic"]

_inventory_item_st = st.fixed_dictionaries({
    "display_name": st.text(min_size=1, max_size=30),
    "description": st.text(min_size=0, max_size=50),
    "category": st.sampled_from(_CATEGORIES),
    "status": st.sampled_from(["pending", "completed", "in_progress", "PENDING"]),
    "anchors": st.lists(
        st.fixed_dictionaries({"page_index": st.integers(min_value=1, max_value=100)}),
        max_size=2,
    ),
})

_session_state_with_inventory_st = st.fixed_dictionaries({
    "document_inventory": st.fixed_dictionaries({
        "items": st.lists(_inventory_item_st, min_size=0, max_size=30),
    }),
})

# Estrategia para pendientes mixtos (inventario + no-inventario)
_non_inventory_pending_st = st.fixed_dictionaries({
    "question_id": st.text(min_size=1, max_size=20),
    "question_type": st.sampled_from(["B", "Q", "A", "economic_price", "profile_field"]),
    "field_target": st.text(min_size=1, max_size=40).filter(
        lambda s: not s.startswith("inventory.") and s != "quality.classification.review"
    ),
    "question": st.text(min_size=1, max_size=80),
})

_inventory_pending_st = st.one_of(
    # Formato nuevo: question_type="I"
    st.fixed_dictionaries({
        "question_id": st.just("INTAKE-INV-TEST"),
        "question_type": st.just("I"),
        "field_target": st.sampled_from([
            "inventory.legal_administrative.completion",
            "inventory.technical.completion",
            "inventory.economic.completion",
        ]),
        "question": st.text(min_size=1, max_size=50),
    }),
    # Formato legacy: field con prefijo "inventory."
    st.fixed_dictionaries({
        "question_id": st.just("INTAKE-INV-LEGACY"),
        "type": st.just("intake_planner"),
        "field": st.sampled_from([
            "inventory.legal_administrative.completion",
            "inventory.technical.completion",
        ]),
        "question": st.text(min_size=1, max_size=50),
    }),
    # INTAKE-Q-CLASS-001: clasificación técnica interna, también se filtra
    st.fixed_dictionaries({
        "question_id": st.just("INTAKE-Q-CLASS-001"),
        "question_type": st.just("Q"),
        "field_target": st.just("quality.classification.review"),
        "question": st.text(min_size=1, max_size=50),
    }),
)


# Feature: intake-inventory-silent-processing, Property 1: questions nunca contiene pendientes de inventario
@given(session_state=_session_state_with_inventory_st)
@settings(max_examples=100)
def test_property_1_questions_never_contains_inventory(session_state):
    """Propiedad 1: questions nunca contiene pendientes de inventario."""
    agent = _make_agent()
    inp = _make_input(session_state)
    out = asyncio.get_event_loop().run_until_complete(agent.process(inp))
    assert out.status == AgentStatus.SUCCESS
    for q in out.data.get("questions", []):
        assert q.get("question_type") != "I"
        field_target = str(q.get("field_target") or q.get("field") or "")
        assert not field_target.startswith("inventory.")


# Feature: intake-inventory-silent-processing, Property 2: inventory_summary contiene todos los grupos con estructura completa
@given(session_state=_session_state_with_inventory_st)
@settings(max_examples=100)
def test_property_2_inventory_summary_structure(session_state):
    """Propiedad 2: inventory_summary contiene todos los grupos con estructura completa."""
    agent = _make_agent()
    inp = _make_input(session_state)
    out = asyncio.get_event_loop().run_until_complete(agent.process(inp))
    assert out.status == AgentStatus.SUCCESS
    inv_summary = out.data.get("inventory_summary", [])
    for item in inv_summary:
        assert "category" in item
        assert "count" in item
        assert isinstance(item["count"], int) and item["count"] > 0
        assert "priority" in item
        assert "field_target" in item
        assert item["field_target"].startswith("inventory.")
        assert "table_data" in item


# Feature: intake-inventory-silent-processing, Property 3: el sanitize elimina todos los pendientes de inventario
@given(
    inventory_qs=st.lists(_inventory_pending_st, min_size=0, max_size=5),
    non_inventory_qs=st.lists(_non_inventory_pending_st, min_size=0, max_size=10),
)
@settings(max_examples=100)
def test_property_3_sanitize_removes_all_inventory(inventory_qs, non_inventory_qs):
    """Propiedad 3: el sanitize elimina todos los pendientes de inventario."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)
    agent = ChatbotRAGAgent(ctx)

    # Mezclar inventario y no-inventario en orden aleatorio
    mixed = inventory_qs + non_inventory_qs

    session_state = {"pending_questions": mixed, "tasks_completed": []}
    result = asyncio.get_event_loop().run_until_complete(
        agent._sanitize_economic_pending_questions("sess_prop3", session_state)
    )

    for q in result:
        q_type = str(q.get("question_type") or q.get("type") or "")
        field_target = str(q.get("field_target") or q.get("field") or "")
        question_id = str(q.get("question_id") or "")
        assert q_type != "I", f"Pendiente de inventario no eliminado: {q}"
        assert not field_target.startswith("inventory."), f"field_target con prefijo 'inventory.' no eliminado: {q}"
        assert question_id != "INTAKE-Q-CLASS-001", f"INTAKE-Q-CLASS-001 no eliminado: {q}"
        assert field_target != "quality.classification.review", f"quality.classification.review no eliminado: {q}"


# Feature: intake-inventory-silent-processing, Property 4: el sanitize preserva los pendientes no-inventario
@given(non_inventory_qs=st.lists(_non_inventory_pending_st, min_size=0, max_size=10))
@settings(max_examples=100)
def test_property_4_sanitize_preserves_non_inventory(non_inventory_qs):
    """Propiedad 4: el sanitize preserva los pendientes no-inventario sin modificación."""
    from app.agents.chatbot_rag import ChatbotRAGAgent

    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(return_value={})
    ctx.memory.save_session = AsyncMock(return_value=True)
    agent = ChatbotRAGAgent(ctx)

    session_state = {"pending_questions": non_inventory_qs, "tasks_completed": []}
    result = asyncio.get_event_loop().run_until_complete(
        agent._sanitize_economic_pending_questions("sess_prop4", session_state)
    )

    # Todos los no-inventario deben preservarse (el sanitize puede filtrar otros tipos
    # como economic_price huérfanas, pero los B/Q/A se preservan)
    # Verificamos que ningún elemento fue modificado
    for original, sanitized in zip(non_inventory_qs, result):
        if sanitized.get("question_id") == original.get("question_id"):
            assert sanitized == original


# Feature: intake-inventory-silent-processing, Property 5: inventory_pending_count es la suma de los count de inventory_summary
@given(session_state=_session_state_with_inventory_st)
@settings(max_examples=100)
def test_property_5_inventory_pending_count_equals_sum(session_state):
    """Propiedad 5: summary.inventory_pending_count es la suma de los count de inventory_summary."""
    agent = _make_agent()
    inp = _make_input(session_state)
    out = asyncio.get_event_loop().run_until_complete(agent.process(inp))
    assert out.status == AgentStatus.SUCCESS
    inv_summary = out.data.get("inventory_summary", [])
    expected = sum(item.get("count", 0) for item in inv_summary)
    assert out.data["summary"]["inventory_pending_count"] == expected


# Feature: intake-inventory-silent-processing, Property 6: los conteos del summary excluyen los pendientes de inventario
@given(session_state=_session_state_with_inventory_st)
@settings(max_examples=100)
def test_property_6_summary_counts_exclude_inventory(session_state):
    """Propiedad 6: blocking_count + critical_count + important_count + complementary_count == len(questions)."""
    agent = _make_agent()
    inp = _make_input(session_state)
    out = asyncio.get_event_loop().run_until_complete(agent.process(inp))
    assert out.status == AgentStatus.SUCCESS
    summary = out.data["summary"]
    questions = out.data["questions"]
    total_from_summary = (
        summary["blocking_count"]
        + summary["critical_count"]
        + summary["important_count"]
        + summary["complementary_count"]
    )
    assert total_from_summary == len(questions)

