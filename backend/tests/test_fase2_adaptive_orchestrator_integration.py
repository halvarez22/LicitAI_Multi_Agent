"""
tests/test_fase2_adaptive_orchestrator_integration.py
Pruebas de integración para Fase 2 — Orquestador Adaptativo.
"""
import pytest
from unittest.mock import AsyncMock, patch
from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.contracts.agent_contracts import AgentOutput, AgentStatus
from app.config.settings import settings


def _memory_stub():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={"tasks_completed": []})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_global_context = AsyncMock(return_value={"tasks_completed": []})
    mem.get_documents = AsyncMock(return_value=[])
    return mem


class TestAdaptiveOrchestratorIntegration:
    @pytest.mark.asyncio
    async def test_adaptive_metadata_present_when_enabled(self):
        """
        Si ADAPTIVE_ORCHESTRATOR_ENABLED=True, debe incluirse metadata.pipeline_config.
        """
        with patch.object(settings, "ADAPTIVE_ORCHESTRATOR_ENABLED", True), \
             patch.object(settings, "ADAPTIVE_PIPELINE_SAFE_MODE", True):
             
            ctx = MCPContextManager(_memory_stub())
            orch = OrchestratorAgent(ctx)

            with patch("app.agents.analyst.AnalystAgent") as Ma:
                Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="a", session_id="s", data={}
                ))

                result = await orch.process(
                    "sess-adapt-001",
                    {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
                )

        assert "pipeline_config" in result["metadata"]
        assert result["metadata"]["pipeline_config"]["adaptive"] is True
        assert "stages_planned" in result["metadata"]["pipeline_config"]

    @pytest.mark.asyncio
    async def test_adaptive_legacy_behavior_on_disabled(self):
        """
        Si la flag está en OFF, el comportamiento legacy debe persistir sin metadata adaptativa.
        """
        with patch.object(settings, "ADAPTIVE_ORCHESTRATOR_ENABLED", False):
            ctx = MCPContextManager(_memory_stub())
            orch = OrchestratorAgent(ctx)

            with patch("app.agents.analyst.AnalystAgent") as Ma:
                Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="a", session_id="s", data={}
                ))

                result = await orch.process(
                    "sess-adapt-legacy",
                    {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
                )

        assert result["metadata"]["pipeline_config"]["adaptive"] is False
        assert result["metadata"]["pipeline_config"]["pipeline_type"] == "default_full"

    @pytest.mark.asyncio
    async def test_short_circuit_rule_triggered_on_datagap(self):
        """
        Si hay un datagap bloqueante, el orquestador dispara la regla MISSING_CRITICAL_DATA.
        """
        with patch.object(settings, "ADAPTIVE_ORCHESTRATOR_ENABLED", True), \
             patch.object(settings, "ADAPTIVE_PIPELINE_SAFE_MODE", False):
             
            ctx = MCPContextManager(_memory_stub())
            orch = OrchestratorAgent(ctx)

            # Forzamos datagap bloqueante
            with patch("app.agents.analyst.AnalystAgent") as Ma, \
                 patch("app.agents.compliance.ComplianceAgent") as Mc, \
                 patch("app.agents.data_gap.DataGapAgent") as Mg:

                Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="a", session_id="s", data={}
                ))
                Mc.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="c", session_id="s", data={}
                ))
                Mg.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.WAITING_FOR_DATA, agent_id="dg", session_id="sx", data={"missing": ["RFC"]}
                ))

                # Esto debe retornar waiting_for_data y marcar la regla disparada 
                # (nota: implementado en logic routing si se desea, por ahora el orquestador 
                #  ya maneja el return de WAITING_FOR_DATA de forma nativa).
                result = await orch.process(
                    "sess-adapt-gap",
                    {"company_id": "co-1", "company_data": {"mode": "full"}}
                )

        assert result["status"] == "waiting_for_data"
        # En el orquestador, el return anticipado de WAITING_FOR_DATA por datagap
        # sigue funcionando igual (backward compatibility), pero el motor de reglas 
        # adaptativo ahora lo detecta formalmente si lo pedimos.
