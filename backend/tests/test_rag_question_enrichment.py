import pytest
import re
from typing import Any, Dict
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from unittest.mock import MagicMock, AsyncMock

from app.agents.chatbot_rag import ChatbotRAGAgent
from app.agents.mcp_context import MCPContextManager

# Mock dependencies for ChatbotRAGAgent
@pytest.fixture
def mock_context_manager():
    return MagicMock(spec=MCPContextManager)

@pytest.fixture
def agent(mock_context_manager):
    return ChatbotRAGAgent(context_manager=mock_context_manager)

# --- Property Tests with Hypothesis ---

# Property 1: _truncate_to_sentence never exceeds max_chars
@settings(max_examples=200)
@given(
    text=st.text(min_size=0, max_size=2000),
    max_chars=st.integers(min_value=10, max_value=1000),
    min_chars=st.integers(min_value=1, max_value=50),
)
def test_truncate_never_exceeds_max_chars(text, max_chars, min_chars):
    assume(min_chars < max_chars)
    result = ChatbotRAGAgent._truncate_to_sentence(text, max_chars, min_chars)
    assert len(result) <= max_chars
    if result:
        assert len(result) >= min_chars

# Property 2: _truncate_to_sentence ends in sentence separator if one exists
SEPARATORS = {'.', '!', '?', ',', ';'}

@settings(max_examples=200)
@given(
    prefix=st.text(min_size=0, max_size=350, alphabet=st.characters(blacklist_characters='.!?,;')),
    sep=st.sampled_from(['.', '!', '?', ',', ';']),
    suffix=st.text(min_size=1, max_size=100, alphabet=st.characters(blacklist_characters='.!?,;')),
)
def test_truncate_ends_in_separator(prefix, sep, suffix):
    # Construir texto que tiene un separador dentro de los primeros 400 chars
    text = prefix + sep + suffix
    result = ChatbotRAGAgent._truncate_to_sentence(text, 400, 1)
    if result:
        # Debería terminar en separador o ser el texto completo truncado
        assert result[-1] in SEPARATORS or result == text[:400].strip()

# Property 3: _is_rag_context_clean rejects namespace patterns
@settings(max_examples=200)
@given(
    word_a=st.from_regex(r'[a-zA-Z_]{2,10}', fullmatch=True),
    word_b=st.from_regex(r'[a-zA-Z_]{2,10}', fullmatch=True),
    surrounding=st.text(min_size=30, max_size=200),
)
def test_clean_rejects_namespace_pattern(word_a, word_b, surrounding):
    text = surrounding + word_a + '.' + word_b + surrounding
    result = ChatbotRAGAgent._is_rag_context_clean(text, min_chars=30)
    assert result is False

def test_clean_allows_numbered_clauses():
    # Anexo 1.1 should be allowed now
    text = "De acuerdo con el Anexo 1.1 de las bases, se solicita un capital contable."
    result = ChatbotRAGAgent._is_rag_context_clean(text, min_chars=10)
    assert result is True

def test_clean_still_rejects_technical_vars():
    # technical vars should still be rejected
    text = "Error en el campo solvencia_legal.rfc detectado."
    result = ChatbotRAGAgent._is_rag_context_clean(text, min_chars=10)
    assert result is False

# Property 4: _build_rag_query includes question for intake_planner
@settings(max_examples=200)
@given(
    question=st.text(min_size=10, max_size=300),
    reason=st.text(min_size=0, max_size=200),
    field_target=st.text(min_size=0, max_size=50),
)
def test_build_query_includes_question_for_intake_planner(question, reason, field_target):
    pq = {
        "type": "intake_planner",
        "question": question,
        "provenance_ui": {"reason": reason},
        "field_target": field_target,
    }
    query = ChatbotRAGAgent._build_rag_query(pq)
    assert question.strip() in query

# Property 5 & 6: Integration tests for _enrich_pending_with_rag_context (using mocks)

@pytest.mark.asyncio
async def test_original_not_mutated_on_failure(agent):
    # Mock vector_db to raise exception
    agent.vector_db.query_texts = MagicMock(side_effect=Exception("DB Failure"))
    
    pq = {"type": "intake_planner", "question": "Test question?", "field_target": "test_field"}
    result = await agent._enrich_pending_with_rag_context("session_123", pq)
    
    # Identidad de objeto preservada
    assert result is pq
    assert "rag_context" not in result

@pytest.mark.asyncio
async def test_high_score_returns_original(agent):
    # Mock vector_db to return high score (low similarity)
    agent.vector_db.query_texts = MagicMock(return_value={
        "documents": ["Some relevant text that is long enough to pass min_chars."],
        "distances": [0.8] # Higher than 0.75 threshold
    })
    
    pq = {"type": "intake_planner", "question": "Test question?", "field_target": "solvencia_economica.capital_contable"}
    result = await agent._enrich_pending_with_rag_context("session_123", pq)
    
    assert result is pq
    assert "rag_context" not in result

# --- Example Tests (pytest) ---

@pytest.mark.asyncio
async def test_enrichment_success_end_to_end(agent):
    # Mock vector_db success
    agent.vector_db.query_texts = MagicMock(return_value={
        "documents": ["De acuerdo con las bases, la penalización por retraso será del 2% diario. Esto es importante."],
        "distances": [0.3]
    })
    
    pq = {
        "type": "structured_field", 
        "field_target": "condiciones_contractuales.penalizaciones",
        "label": "Penalizaciones"
    }
    result = await agent._enrich_pending_with_rag_context("session_123", pq)
    
    assert result is not pq
    assert "rag_context" in result
    assert "2% diario" in result["rag_context"]
    assert result["rag_context"].endswith(".") # Truncated to sentence

@pytest.mark.asyncio
async def test_domain_terms_inclusion(agent):
    pq = {
        "type": "structured_field",
        "field_target": "solvencia_economica.capital_contable"
    }
    query = ChatbotRAGAgent._build_rag_query(pq)
    assert "capital contable" in query
    assert "patrimonio" in query # From _DOMAIN_TERMS_MAP

@pytest.mark.asyncio
async def test_technical_variable_filtering(agent):
    # Fragment contains technical namespace
    agent.vector_db.query_texts = MagicMock(return_value={
        "documents": ["Requisito fallido: solvencia_legal.rfc no debe aparecer aquí. Es técnico."],
        "distances": [0.2]
    })
    
    pq = {"type": "intake_planner", "question": "RFC?", "field_target": "solvencia_legal.rfc"}
    result = await agent._enrich_pending_with_rag_context("session_123", pq)
    
    # Should reject due to technical variable
    assert result is pq
    assert "rag_context" not in result

@pytest.mark.asyncio
async def test_non_enrichable_types(agent):
    pq = {"type": "economic_price", "question": "Precio?"}
    result = await agent._enrich_pending_with_rag_context("session_123", pq)
    assert result is pq
