"""
test_fase0_contracts.py
Tests unitarios para los contratos estrictos de Fase 0.
Valida: AgentInput, AgentOutput, OrchestratorState, SessionStateV1
"""
import pytest
from pydantic import ValidationError

from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus
from app.contracts.orchestrator_contracts import OrchestratorState
from app.contracts.session_contracts import SessionStateV1, SessionStateMigrator


# ─── AgentInput ──────────────────────────────────────────────────────────────

class TestAgentInput:
    def test_valid_input_accepted(self):
        inp = AgentInput(session_id="sess-001", mode="full")
        assert inp.session_id == "sess-001"
        assert inp.mode == "full"

    def test_extra_field_forbidden(self):
        """Payload con campo extra debe fallar con extra='forbid'."""
        with pytest.raises(ValidationError) as exc_info:
            AgentInput(
                session_id="sess-001",
                mode="full",
                campo_inventado="debería_fallar"
            )
        assert "extra" in str(exc_info.value).lower() or "campo_inventado" in str(exc_info.value)

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            AgentInput(session_id="sess-001", mode="modo_inventado")
        assert "modo_inventado" in str(exc_info.value) or "Modo inválido" in str(exc_info.value)

    def test_all_valid_modes_accepted(self):
        for mode in ("full", "analysis_only", "generation", "generation_only"):
            inp = AgentInput(session_id="s", mode=mode)
            assert inp.mode == mode

    def test_empty_session_id_rejected(self):
        with pytest.raises(ValidationError):
            AgentInput(session_id="", mode="full")

    def test_optional_fields_have_defaults(self):
        inp = AgentInput(session_id="sess-001")
        assert inp.company_id is None
        assert inp.company_data == {}
        assert inp.correlation_id is None


# ─── AgentOutput ─────────────────────────────────────────────────────────────

class TestAgentOutput:
    def test_valid_success_output(self):
        out = AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id="analyst_001",
            session_id="sess-001",
            data={"cronograma": {}}
        )
        assert out.status == AgentStatus.SUCCESS

    def test_error_status_without_message_fails(self):
        """ERROR status sin mensaje debe fallar validación."""
        with pytest.raises(ValidationError):
            AgentOutput(
                status=AgentStatus.ERROR,
                agent_id="analyst_001",
                session_id="sess-001",
            )

    def test_error_status_with_message_ok(self):
        out = AgentOutput(
            status=AgentStatus.ERROR,
            agent_id="compliance_001",
            session_id="sess-001",
            error="Timeout al llamar al LLM"
        )
        assert out.error == "Timeout al llamar al LLM"

    def test_confidence_score_range_0_to_1(self):
        """Confidence score fuera de [0,1] debe fallar."""
        with pytest.raises(ValidationError):
            AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="analyst_001",
                session_id="sess-001",
                confidence_score=1.5
            )
        with pytest.raises(ValidationError):
            AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="analyst_001",
                session_id="sess-001",
                confidence_score=-0.1
            )

    def test_to_legacy_dict_backward_compat(self):
        """to_legacy_dict() debe producir formato compatible con pipeline actual."""
        out = AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id="analyst_001",
            session_id="sess-001",
            data={"cronograma": {"junta": "01/01/2026"}}
        )
        legacy = out.to_legacy_dict()
        assert legacy["status"] == "success"
        assert "data" in legacy
        assert "cronograma" in legacy["data"]

    def test_all_status_values_accepted(self):
        for st in AgentStatus:
            kw = {"error": "test"} if st == AgentStatus.ERROR else {}
            out = AgentOutput(
                status=st,
                agent_id="x",
                session_id="s",
                **kw
            )
            assert out.status == st


# ─── OrchestratorState ───────────────────────────────────────────────────────

class TestOrchestratorState:
    def test_valid_state(self):
        state = OrchestratorState(
            stop_reason="ANALYSIS_COMPLETED",
            aggregate_health="ok",
            agent_status={"analyst": "success", "compliance": "partial"}
        )
        assert state.aggregate_health == "ok"

    def test_extra_field_forbidden(self):
        with pytest.raises(ValidationError):
            OrchestratorState(
                stop_reason="DONE",
                aggregate_health="ok",
                agent_status={},
                campo_no_existe="x"
            )

    def test_serializable_to_dict(self):
        state = OrchestratorState(
            stop_reason="COMPLIANCE_ERROR",
            aggregate_health="failed",
            agent_status={"compliance": "error"}
        )
        d = state.model_dump()
        assert d["stop_reason"] == "COMPLIANCE_ERROR"
        assert d["aggregate_health"] == "failed"


# ─── SessionStateV1 + Migrator ───────────────────────────────────────────────

class TestSessionStateMigrator:
    def test_estado_v0_sin_version_migra_a_v1(self):
        """Estado legacy sin schema_version se migra correctamente."""
        v0_state = {
            "status": "initialized",
            "global_inputs": {"company_id": "co-001"},
            "tasks_completed": [{"task": "analisis_bases", "result": {}}],
            # Sin schema_version — es un estado v0
        }
        migrated, was_migrated = SessionStateMigrator.migrate("sess-001", v0_state)

        assert was_migrated is True
        assert migrated["schema_version"] == 1
        assert migrated["status"] == "initialized"
        assert migrated["global_inputs"]["company_id"] == "co-001"
        assert len(migrated["tasks_completed"]) == 1

    def test_estado_v0_preserva_datos_existentes(self):
        """La migración no destruye datos del estado original."""
        v0_state = {
            "status": "running",
            "tasks_completed": [{"task": "t1"}],
            "generation_state": {"jobs": []},
            "checklist": [{"req_id": "AD-01"}],
            "last_orchestrator_decision": {"stop_reason": "ANALYSIS_COMPLETED"},
            "campo_extra_custom": "valor_custom",  # campo no estándar
        }
        migrated, was_migrated = SessionStateMigrator.migrate("sess-001", v0_state)

        assert was_migrated is True
        assert migrated["tasks_completed"] == [{"task": "t1"}]
        assert migrated["generation_state"] == {"jobs": []}
        assert migrated["checklist"] == [{"req_id": "AD-01"}]
        # Campos extra deben preservarse
        assert migrated.get("campo_extra_custom") == "valor_custom"

    def test_estado_v1_no_remigra(self):
        """Estado ya en v1 no necesita migración."""
        v1_state = {"schema_version": 1, "status": "ok", "tasks_completed": []}
        migrated, was_migrated = SessionStateMigrator.migrate("sess-001", v1_state)

        assert was_migrated is False
        assert migrated is v1_state  # mismo objeto

    def test_estado_none_inicializa_v1(self):
        """Estado None (sesión nueva) se inicializa como v1."""
        migrated, was_migrated = SessionStateMigrator.migrate("sess-nueva", None)

        assert was_migrated is True
        assert migrated["schema_version"] == 1
        assert migrated["status"] == "initialized"
        assert migrated["tasks_completed"] == []

    def test_session_state_v1_to_dict_completo(self):
        state = SessionStateV1(
            schema_version=1,
            status="running",
            global_inputs={"company_id": "co-1"},
            tasks_completed=[{"task": "x"}],
        )
        d = state.to_dict()
        assert d["schema_version"] == 1
        assert d["global_inputs"]["company_id"] == "co-1"
