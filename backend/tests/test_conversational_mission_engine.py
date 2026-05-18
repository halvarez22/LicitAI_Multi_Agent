"""
test_conversational_mission_engine.py — Tests unitarios y PBT para conversational-mission-engine.

Verifica que:
- _humanize_field_target nunca retorna namespace técnico
- _build_mission_context siempre retorna exactamente 7 claves
- _detect_tone_mode detecta correctamente los 4 modos
- El motor conversacional es resiliente ante inputs inválidos
"""
from __future__ import annotations

import re
import sys
import os

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from unittest.mock import MagicMock

# Asegurar que el path de backend está disponible
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chatbot_rag import ChatbotRAGAgent


# ---------------------------------------------------------------------------
# Estrategias de Hypothesis
# ---------------------------------------------------------------------------

_field_target_technical_st = st.from_regex(
    r"[a-z][a-z_]{1,20}\.[a-z][a-z_]{1,20}",
    fullmatch=True,
)

_field_target_any_st = st.one_of(
    _field_target_technical_st,
    st.text(min_size=0, max_size=80),
    st.just(""),
    st.just("solvencia_legal.rfc"),
    st.just("condiciones_contractuales.penalizaciones"),
    st.just("quality.fill.review"),
)

_pending_question_st = st.fixed_dictionaries({
    "label": st.one_of(st.text(min_size=0, max_size=80), st.just("")),
    "question": st.text(min_size=0, max_size=200),
    "is_blocking": st.booleans(),
    "field_target": st.one_of(_field_target_technical_st, st.just("")),
    "provenance_ui": st.one_of(
        st.fixed_dictionaries({"reason": st.text(min_size=0, max_size=80)}),
        st.just({}),
        st.just(None),
    ),
})

_session_state_st = st.fixed_dictionaries({
    "tasks_completed": st.lists(
        st.fixed_dictionaries({
            "task": st.one_of(
                st.from_regex(r"stage_completed:[a-z_]+", fullmatch=True),
                st.text(min_size=1, max_size=40),
            )
        }),
        min_size=0,
        max_size=5,
    ),
    "go_no_go_result": st.one_of(
        st.fixed_dictionaries({"semaforo": st.sampled_from(["RED", "YELLOW", "GREEN", ""])}),
        st.just({}),
        st.just(None),
    ),
})


# ---------------------------------------------------------------------------
# Tests unitarios — Tarea 7
# ---------------------------------------------------------------------------

class TestHumanizeFieldTarget:
    """test_humanize_field_target_exact_match y variantes."""

    def test_exact_match_penalizaciones(self):
        result = ChatbotRAGAgent._humanize_field_target("condiciones_contractuales.penalizaciones")
        assert result == "Penalizaciones contractuales"

    def test_exact_match_rfc(self):
        result = ChatbotRAGAgent._humanize_field_target("solvencia_legal.rfc")
        assert result == "RFC de la empresa"

    def test_exact_match_capital_contable(self):
        result = ChatbotRAGAgent._humanize_field_target("solvencia_economica.capital_contable")
        assert result == "Capital contable mínimo"

    def test_exact_match_quality_classification(self):
        result = ChatbotRAGAgent._humanize_field_target("quality.classification.review")
        assert result == "Revisión de clasificación documental"

    def test_exact_match_quality_fill(self):
        result = ChatbotRAGAgent._humanize_field_target("quality.fill.review")
        assert result == "Validación de llenado documental"

    def test_prefix_match_solvencia_economica(self):
        """test_humanize_field_target_prefix_match"""
        result = ChatbotRAGAgent._humanize_field_target("solvencia_economica.nuevo_campo_desconocido")
        assert "Solvencia económica" in result
        assert "solvencia_economica" not in result
        assert "." not in result or not re.search(r"\w+\.\w+", result)

    def test_prefix_match_condiciones_contractuales(self):
        result = ChatbotRAGAgent._humanize_field_target("condiciones_contractuales.nuevo_campo")
        assert "Condición contractual" in result
        assert "condiciones_contractuales" not in result

    def test_prefix_match_inventory(self):
        result = ChatbotRAGAgent._humanize_field_target("inventory.legal_administrative.completion")
        assert "Inventario documental" in result
        assert "inventory." not in result

    def test_generic_cleanup_unknown_namespace(self):
        """test_humanize_field_target_generic_cleanup"""
        result = ChatbotRAGAgent._humanize_field_target("namespace_desconocido.campo_especifico")
        # Debe eliminar el namespace y limpiar
        assert "namespace_desconocido" not in result or "." not in result
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_string_returns_dato_requerido(self):
        """test_humanize_field_target_empty_input"""
        assert ChatbotRAGAgent._humanize_field_target("") == "Dato requerido"

    def test_none_returns_dato_requerido(self):
        assert ChatbotRAGAgent._humanize_field_target(None) == "Dato requerido"

    def test_no_dot_string_returned_as_is_cleaned(self):
        result = ChatbotRAGAgent._humanize_field_target("capital_contable")
        assert isinstance(result, str)
        assert len(result) > 0
        # Sin punto, no hay namespace que eliminar
        assert "capital_contable" not in result or result == "Capital contable"


class TestBuildMissionContext:
    def setup_method(self):
        self.agent = ChatbotRAGAgent(MagicMock())

    def test_returns_exactly_7_keys(self):
        """test_build_mission_context_blocking"""
        ctx = self.agent._build_mission_context(
            {}, {"label": "RFC", "question": "¿RFC?", "is_blocking": False}, 0, 5
        )
        assert len(ctx) == 7
        assert set(ctx.keys()) == {
            "dato_solicitado", "por_que_importa", "impacto",
            "progreso", "documentos_generados", "semaforo_actual", "provenance_reason"
        }

    def test_blocking_true_sets_impacto_bloqueante(self):
        ctx = self.agent._build_mission_context(
            {}, {"label": "Capital", "question": "¿Capital?", "is_blocking": True}, 0, 3
        )
        assert ctx["impacto"] == "BLOQUEANTE"

    def test_blocking_false_sets_impacto_complementario(self):
        ctx = self.agent._build_mission_context(
            {}, {"label": "Web", "question": "¿Web?", "is_blocking": False}, 0, 3
        )
        assert ctx["impacto"] == "complementario"

    def test_docs_generated_true_when_stage_completed(self):
        """test_build_mission_context_docs_generated"""
        ss = {"tasks_completed": [{"task": "stage_completed:analysis"}]}
        ctx = self.agent._build_mission_context(
            ss, {"label": "RFC", "question": "¿RFC?"}, 0, 1
        )
        assert ctx["documentos_generados"] is True

    def test_docs_generated_false_when_no_stage_completed(self):
        ss = {"tasks_completed": [{"task": "go_no_go_result"}]}
        ctx = self.agent._build_mission_context(
            ss, {"label": "RFC", "question": "¿RFC?"}, 0, 1
        )
        assert ctx["documentos_generados"] is False

    def test_empty_session_state_no_exception(self):
        """test_build_mission_context_empty_state"""
        ctx = self.agent._build_mission_context({}, {}, 0, 1)
        assert len(ctx) == 7
        assert ctx["documentos_generados"] is False
        assert ctx["semaforo_actual"] == ""

    def test_progreso_format(self):
        ctx = self.agent._build_mission_context({}, {"label": "X"}, 2, 10)
        assert ctx["progreso"] == "3 de 10"

    def test_label_humanized_in_dato_solicitado(self):
        ctx = self.agent._build_mission_context(
            {}, {"label": "solvencia_legal.rfc", "question": "¿RFC?"}, 0, 1
        )
        assert ctx["dato_solicitado"] == "RFC de la empresa"
        assert "solvencia_legal" not in ctx["dato_solicitado"]


class TestDetectToneMode:
    def test_modo_completado_when_no_pending(self):
        """test_detect_tone_mode_completado"""
        assert ChatbotRAGAgent._detect_tone_mode({}, [], 0) == "modo_completado"

    def test_modo_post_generacion_when_docs_generated(self):
        """test_detect_tone_mode_post_generacion"""
        ss = {"tasks_completed": [{"task": "stage_completed:analysis"}]}
        result = ChatbotRAGAgent._detect_tone_mode(ss, [{"is_blocking": True}], 0)
        assert result == "modo_post_generacion"

    def test_modo_post_generacion_priority_over_urgente(self):
        """modo_post_generacion tiene prioridad sobre modo_recoleccion_urgente"""
        ss = {"tasks_completed": [{"task": "stage_completed:analysis"}]}
        result = ChatbotRAGAgent._detect_tone_mode(ss, [{"is_blocking": True}], 0)
        assert result == "modo_post_generacion"

    def test_modo_recoleccion_urgente_when_blocking(self):
        """test_detect_tone_mode_urgente"""
        result = ChatbotRAGAgent._detect_tone_mode({}, [{"is_blocking": True}], 0)
        assert result == "modo_recoleccion_urgente"

    def test_modo_recoleccion_inicial_default(self):
        """test_detect_tone_mode_inicial"""
        result = ChatbotRAGAgent._detect_tone_mode({}, [{"is_blocking": False}], 0)
        assert result == "modo_recoleccion_inicial"

    def test_modo_recoleccion_inicial_when_no_is_blocking_field(self):
        result = ChatbotRAGAgent._detect_tone_mode({}, [{}], 0)
        assert result == "modo_recoleccion_inicial"

    def test_no_exception_with_invalid_idx(self):
        """No debe lanzar excepción con índice fuera de rango"""
        result = ChatbotRAGAgent._detect_tone_mode({}, [{"is_blocking": True}], 999)
        assert result in ("modo_recoleccion_inicial", "modo_recoleccion_urgente", "modo_post_generacion", "modo_completado")

    def test_post_generation_message_not_cold(self):
        """test_post_generation_message_not_cold: modo_post_generacion no es el texto frío"""
        ss = {"tasks_completed": [{"task": "stage_completed:analysis"}]}
        mode = ChatbotRAGAgent._detect_tone_mode(ss, [{"is_blocking": False}], 0)
        assert mode == "modo_post_generacion"
        # El modo post_generacion garantiza que el fallback usa tono celebratorio
        # (verificado en TestGenerateMissionQuestion)


# ---------------------------------------------------------------------------
# Tests de propiedades — Tarea 6
# ---------------------------------------------------------------------------

# Feature: conversational-mission-engine, Propiedad 1: _humanize_field_target nunca retorna namespace técnico
@given(field_target=_field_target_technical_st)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_property_1_humanize_never_returns_namespace(field_target):
    """
    Para cualquier field_target técnico (patrón namespace.campo),
    _humanize_field_target nunca retorna un string con ese patrón.
    """
    result = ChatbotRAGAgent._humanize_field_target(field_target)
    assert isinstance(result, str)
    assert len(result) > 0
    # El resultado no debe contener el patrón namespace.campo
    assert not re.search(r"\b[a-z][a-z_]+\.[a-z][a-z_]+\b", result), (
        f"Namespace técnico en resultado: '{result}' para input: '{field_target}'"
    )


# Feature: conversational-mission-engine, Propiedad 2: modo_post_generacion cuando hay stage_completed
@given(
    task_name=st.from_regex(r"stage_completed:[a-z_]+", fullmatch=True),
    pending_q=_pending_question_st,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_2_post_generacion_when_stage_completed(task_name, pending_q):
    """
    Para cualquier session_state con tasks_completed que contiene stage_completed:*,
    _detect_tone_mode retorna modo_post_generacion.
    """
    session_state = {"tasks_completed": [{"task": task_name}]}
    mode = ChatbotRAGAgent._detect_tone_mode(session_state, [pending_q], 0)
    assert mode == "modo_post_generacion"


# Feature: conversational-mission-engine, Propiedad 3: modo_recoleccion_urgente cuando is_blocking=True sin docs
@given(
    pending_q=_pending_question_st.filter(lambda q: q.get("is_blocking") is True),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_3_urgente_when_blocking_no_docs(pending_q):
    """
    Para cualquier pending_question con is_blocking=True y sin documentos generados,
    _detect_tone_mode retorna modo_recoleccion_urgente.
    """
    session_state = {}  # Sin tasks_completed → sin docs generados
    mode = ChatbotRAGAgent._detect_tone_mode(session_state, [pending_q], 0)
    assert mode == "modo_recoleccion_urgente"


# Feature: conversational-mission-engine, Propiedad 4: _humanize_field_target nunca retorna namespace para ningún input
@given(field_target=_field_target_any_st)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_property_4_humanize_never_returns_namespace_any_input(field_target):
    """
    Para cualquier string (incluyendo vacíos, con múltiples puntos, con guiones bajos),
    _humanize_field_target retorna un string no vacío sin patrón namespace.campo.
    """
    result = ChatbotRAGAgent._humanize_field_target(field_target)
    assert isinstance(result, str)
    assert len(result) > 0
    # No debe contener patrón namespace.campo técnico (word.word con underscore)
    assert not re.search(r"\b[a-z][a-z_]+\.[a-z][a-z_]+\b", result), (
        f"Namespace técnico en resultado: '{result}' para input: '{field_target}'"
    )


# Feature: conversational-mission-engine, Propiedad 5: modo_recoleccion_inicial cuando no hay docs y dato no bloqueante
@given(
    pending_q=_pending_question_st.filter(lambda q: not q.get("is_blocking")),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_property_5_inicial_when_no_docs_no_blocking(pending_q):
    """
    Para cualquier pending_question con is_blocking=False/None y sin documentos generados,
    _detect_tone_mode retorna modo_recoleccion_inicial.
    """
    session_state = {}
    mode = ChatbotRAGAgent._detect_tone_mode(session_state, [pending_q], 0)
    assert mode == "modo_recoleccion_inicial"


# Feature: conversational-mission-engine, Propiedad 6: _build_mission_context siempre retorna exactamente 7 claves
@given(
    session_state=_session_state_st,
    pending_q=_pending_question_st,
    current_idx=st.integers(min_value=0, max_value=20),
    total=st.integers(min_value=1, max_value=30),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
def test_property_6_build_mission_context_always_7_keys(session_state, pending_q, current_idx, total):
    """
    Para cualquier combinación de session_state y pending_question,
    _build_mission_context retorna exactamente 7 claves sin lanzar excepciones.
    """
    agent = ChatbotRAGAgent(MagicMock())
    ctx = agent._build_mission_context(session_state, pending_q, current_idx, total)
    assert isinstance(ctx, dict)
    assert len(ctx) == 7
    assert set(ctx.keys()) == {
        "dato_solicitado", "por_que_importa", "impacto",
        "progreso", "documentos_generados", "semaforo_actual", "provenance_reason"
    }
    # impacto siempre es uno de los dos valores válidos
    assert ctx["impacto"] in ("BLOQUEANTE", "complementario")
    # documentos_generados siempre es bool
    assert isinstance(ctx["documentos_generados"], bool)
