"""Regresión HRU: FSR universal vía contratos versionados (sin entrevista legacy)."""

from app.agents.chatbot_rag import ChatbotRAGAgent
from app.services.economic_fsr_policy import (
    chat_capture_patterns,
    extract_fsr_params_from_reglas,
    policy_version,
    required_fsr_param_keys,
)
from app.services.economic_fsr_ux import (
    build_fsr_blocking_chat_message,
    build_fsr_pending_question,
    messages_version,
)
from unittest.mock import MagicMock


def test_fsr_policy_has_required_keys():
    keys = required_fsr_param_keys()
    assert "imss" in keys
    assert "aguinaldo_dias" in keys
    assert policy_version().startswith("economic-fsr-")


def test_fsr_extract_from_reglas_no_invent_imss():
    out = extract_fsr_params_from_reglas({})
    assert "imss" not in out
    assert out.get("sar") == "0.02"


def test_fsr_extract_from_reglas_reads_bases():
    reglas = {"otras_reglas_oferta_precio": "imss=0.245 sar=0.02 aguinaldo_dias=15"}
    out = extract_fsr_params_from_reglas(reglas)
    assert out.get("imss") == "0.245"
    assert out.get("aguinaldo_dias") == "15"


def test_fsr_ux_blocking_message_no_hardcoded_examples():
    issues = ["fsr_required_params_missing: Faltan parámetros FSR (imss, aguinaldo_dias)."]
    msg = build_fsr_blocking_chat_message(blocking_issues=issues, session_state={"name": "Demo"})
    assert "374" not in msg
    assert "vigilancia" not in msg.lower()
    assert "cuota patronal IMSS" in msg
    assert messages_version().startswith("economic-fsr-")


def test_fsr_pending_question_has_stable_error_type():
    issues = ["fsr_required_params_missing: Faltan parámetros FSR (imss)."]
    q = build_fsr_pending_question(blocking_issues=issues)
    assert q["error_type"] == "fsr_required_params_missing"
    assert q["type"] == "economic_validation_blocking"
    assert q["blocking_items"] == ["imss"]


def test_chat_capture_patterns_loaded_from_policy():
    patterns = chat_capture_patterns()
    assert "imss" in patterns
    assert "aguinaldo_dias" in patterns


def test_wants_economic_materialization_ignores_legacy_labor_interview_step():
    agent = ChatbotRAGAgent(context_manager=MagicMock())
    state = {
        "economic_user_inputs": {f"price_{i}": 1000 + i for i in range(8)},
        "pending_questions": [],
        "labor_compliance_interview_step": "step_2_imss_risk",
    }
    assert agent._wants_economic_materialization("generar propuesta economica", state) is True


def test_no_labor_compliance_interview_handlers():
    assert not hasattr(ChatbotRAGAgent, "_handle_labor_compliance_interview")
    assert not hasattr(ChatbotRAGAgent, "_labor_compliance_interview_reminder")
