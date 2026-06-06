"""Prioridad de aclaración HITL sobre RAG cuando hay cola pendiente."""
from __future__ import annotations

from app.agents.chatbot_rag import ChatbotRAGAgent, _looks_like_bases_clarification_query


def test_clarification_intent_with_question_mark():
    assert ChatbotRAGAgent._evaluate_clarification_intent("claro dime que datos necesitas?")
    assert not _looks_like_bases_clarification_query("claro dime que datos necesitas?")


def test_bases_query_still_detected_with_anexo():
    q = "¿Qué dice el Anexo III sobre muestras en las bases?"
    assert _looks_like_bases_clarification_query(q)
