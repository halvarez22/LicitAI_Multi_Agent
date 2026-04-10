"""
test_fase0_integration.py
Tests de integración de Fase 0 — backward compatibility y contratos en pipeline.

Valida:
  1. Pipeline legacy (sin flags nuevas) corre sin romperse
  2. Pipeline hardened (con contratos) produce AgentOutput válido en Analyst+Compliance
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.contracts.agent_contracts import AgentOutput, AgentStatus
from app.contracts.session_contracts import SessionStateMigrator


def _memory_stub(session: dict | None = None):
    mem = AsyncMock()
    sess = session if session is not None else {"tasks_completed": []}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.record_task_completion = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem


# ─── Test de integración 1: Pipeline legacy sin activar flags nuevas ─────────

class TestLegacyPipelineCompatibility:
    @pytest.mark.asyncio
    async def test_pipeline_legacy_corre_sin_flags_nuevas(self):
        """
        Flujo actual (dict libre) NO debe romperse con la Fase 0.
        Los contratos son opt-in vía to_legacy_dict(), no forzados aún en el orchestrator.
        """
        ctx = MCPContextManager(_memory_stub())
        orch = OrchestratorAgent(ctx)

        with patch("app.agents.analyst.AnalystAgent") as Ma, \
             patch("app.agents.compliance.ComplianceAgent") as Mc, \
             patch("app.agents.economic.EconomicAgent") as Me:

            Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="analyst_mock",
                session_id="sess-legacy-001",
                data={"cronograma": {}}
            ))
            Mc.return_value.process = AsyncMock(return_value=AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="compliance_mock",
                session_id="sess-legacy-001",
                data={"administrativo": [{"id": "AD-01", "estado": "pass"}], "tecnico": [], "formatos": []}
            ))
            Me.return_value.process = AsyncMock(return_value=AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="economic_mock",
                session_id="sess-legacy-001",
                data={"items": [], "grand_total": 0}
            ))

            result = await orch.process(
                "sess-legacy-001",
                {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
            )

        # El pipeline legacy debe seguir funcionando exactamente igual
        assert result["status"] == "success"
        assert "analysis" in result["results"]
        assert "compliance" in result["results"]
        assert result["orchestrator_decision"]["aggregate_health"] == "ok"


# ─── Test de integración 2: Contratos validan output de agentes ──────────────

class TestHardenedAgentContracts:
    def test_analyst_output_wrappable_en_agent_output(self):
        """
        El output del AnalystAgent existente puede envolvarse en AgentOutput
        sin pérdida de datos — preparación para la migración gradual.
        """
        legacy_output = {
            "status": "success",
            "agent": "analyst_001",
            "data": {
                "cronograma": {"junta_aclaraciones": "01/02/2026"},
                "requisitos_participacion": [],
                "requisitos_filtro": ["RFC"],
                "reglas_economicas": {},
                "alcance_operativo": [],
                "garantias": {"seriedad_oferta": "5%"},
                "criterios_evaluacion": "Puntos y Porcentajes"
            }
        }

        # Envolver en contrato estricto
        wrapped = AgentOutput(
            status=AgentStatus.SUCCESS,
            agent_id="analyst_001",
            session_id="sess-001",
            data=legacy_output["data"]
        )

        assert wrapped.status == AgentStatus.SUCCESS
        assert wrapped.data["cronograma"]["junta_aclaraciones"] == "01/02/2026"

        # to_legacy_dict() reproduce el formato original
        legacy = wrapped.to_legacy_dict()
        assert legacy["status"] == "success"
        assert "data" in legacy

    def test_compliance_partial_output_wrappable(self):
        """Output de compliance con status=partial se envuelve correctamente."""
        compliance_output = {
            "status": "partial",
            "data": {"administrativo": [{"id": "AD-01"}], "tecnico": [], "formatos": []},
            "error": "Auditoría con incidencias. Fallos en: TÉCNICO/OPERATIVO"
        }

        wrapped = AgentOutput(
            status=AgentStatus.PARTIAL,
            agent_id="compliance_001",
            session_id="sess-001",
            data=compliance_output["data"],
            error=compliance_output["error"]
        )
        assert wrapped.status == AgentStatus.PARTIAL
        assert len(wrapped.data["administrativo"]) == 1

    def test_session_state_migrated_on_load(self):
        """
        Cuando el orchestrator carga un estado legacy (v0), el migrador
        lo convierte a v1 sin perder datos.
        """
        legacy_session = {
            # Sin schema_version — es v0
            "status": "initialized",
            "global_inputs": {"company_id": "co-001"},
            "tasks_completed": [
                {"task": "analisis_bases", "result": {"cronograma": {}}}
            ],
            "last_orchestrator_decision": {"stop_reason": "ANALYSIS_COMPLETED"}
        }

        migrated, was_migrated = SessionStateMigrator.migrate("sess-v0", legacy_session)

        assert was_migrated is True
        assert migrated["schema_version"] == 1
        # Datos originales preservados
        assert migrated["global_inputs"]["company_id"] == "co-001"
        assert migrated["tasks_completed"][0]["task"] == "analisis_bases"
        assert migrated["last_orchestrator_decision"]["stop_reason"] == "ANALYSIS_COMPLETED"

    @pytest.mark.asyncio
    async def test_orchestrator_detiene_compliance_error_contrato_intacto(self):
        """Regresión: comportamiento de COMPLIANCE_ERROR no cambia con Fase 0."""
        ctx = MCPContextManager(_memory_stub())
        orch = OrchestratorAgent(ctx)

        with patch("app.agents.analyst.AnalystAgent") as Ma, \
             patch("app.agents.compliance.ComplianceAgent") as Mc, \
             patch("app.agents.economic.EconomicAgent") as Me:

            Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="analyst_mock",
                session_id="sess-compliance-error",
                data={}
            ))
            Mc.return_value.process = AsyncMock(side_effect=RuntimeError("compliance boom"))
            Me.return_value.process = AsyncMock(return_value=AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="economic_mock",
                session_id="sess-compliance-error",
                data={}
            ))

            result = await orch.process(
                "sess-compliance-error",
                {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
            )

        assert result["orchestrator_decision"]["stop_reason"] == "COMPLIANCE_GATE_BLOCKING"
        assert result["orchestrator_decision"]["aggregate_health"] == "failed"
        Me.return_value.process.assert_not_awaited()
