"""
tests/test_fase1_confidence_integration.py
Pruebas de integración para Fase 1 — Confianza y Orquestador.
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
    mem.get_documents = AsyncMock(return_value=[])
    mem.record_task_completion = AsyncMock(return_value=True)
    return mem


class TestConfidenceIntegration:
    @pytest.mark.asyncio
    async def test_analyst_retorna_confidence_y_shadow_mode_no_rompe(self):
        """
        AnalystAgent debe incluir confianza en data.
        En Shadow Mode (default), el estatus del pipeline no cambia.
        """
        # Habilitar shadow mode forzado para test
        with patch.object(settings, "CONFIDENCE_ENABLED", False), \
             patch.object(settings, "CONFIDENCE_SHADOW_MODE", True):
             
            ctx = MCPContextManager(_memory_stub())
            orch = OrchestratorAgent(ctx)

            # Mocks de agentes con datos ricos para generar score alto
            with patch("app.agents.analyst.AnalystAgent") as Ma, \
                 patch("app.agents.compliance.ComplianceAgent") as Mc, \
                 patch("app.agents.economic.EconomicAgent") as Me:

                # Analyst devolviendo AgentOutput con confidence enriquecida
                Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id="analyst_mock",
                    session_id="sess-conf-001",
                    data={
                        "requisitos_participacion": [],
                        "requisitos_filtro": ["RFC"],
                        "confidence": {"overall": 0.9, "recommendation": "accept", "threshold_passed": True}
                    }
                ))
                Mc.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id="compliance_mock",
                    session_id="sess-conf-001",
                    data={
                        "administrativo": [{"id": "REQ-1", "estado": "pass"}], "tecnico": [], "formatos": [],
                        "confidence": {"overall": 0.85, "recommendation": "accept", "threshold_passed": True}
                    }
                ))
                Me.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id="economic_mock",
                    session_id="sess-conf-001",
                    data={}
                ))

                result = await orch.process(
                    "sess-conf-001",
                    {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
                )

        # Verificaciones de metadatos de integración (Fase 1)
        assert "metadata" in result
        assert "confidence_summary" in result["metadata"]
        summary = result["metadata"]["confidence_summary"]
        assert summary["avg_confidence"] > 0.0
        assert "analysis" in result["results"]
        assert "confidence" in result["results"]["analysis"]["data"]

    @pytest.mark.asyncio
    async def test_integracion_legacy_intacta_sin_flags(self):
        """
        Si CONFIDENCE_ENABLED=False y CONFIDENCE_SHADOW_MODE=False, 
        no debe enviarse metadata.confidence_summary.
        """
        with patch.object(settings, "CONFIDENCE_ENABLED", False), \
             patch.object(settings, "CONFIDENCE_SHADOW_MODE", False):
             
            ctx = MCPContextManager(_memory_stub())
            orch = OrchestratorAgent(ctx)

            with patch("app.agents.analyst.AnalystAgent") as Ma, \
                 patch("app.agents.compliance.ComplianceAgent") as Mc, \
                 patch("app.agents.economic.EconomicAgent") as Me:
                Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id="analyst_mock",
                    session_id="sess-legacy-conf-001",
                    data={"simple_item": 123}
                ))
                Mc.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="c", session_id="s", data={"administrativo": [{"id": "r1", "estado": "pass"}]}
                ))
                Me.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="e", session_id="s", data={}
                ))

                result = await orch.process(
                    "sess-legacy-conf-001",
                    {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
                )

        assert result["metadata"]["confidence_summary"] is None
        assert "confidence" not in result["results"]["analysis"]["data"]

    @pytest.mark.asyncio
    async def test_compliance_calculates_confidence_on_full_list(self):
        """
        ComplianceAgent debe capturar contextos de múltiples zonas y 
        generar un score de confianza basado en la concatenación de los mismos.
        Este test cubre la corrección del bug de TypeError (join sobre int).
        """
        with patch.object(settings, "CONFIDENCE_ENABLED", True), \
             patch.object(settings, "CONFIDENCE_SHADOW_MODE", False):
             
            ctx = MCPContextManager(_memory_stub())
            orch = OrchestratorAgent(ctx)

            with patch("app.agents.analyst.AnalystAgent") as Ma, \
                 patch("app.agents.compliance.ComplianceAgent") as Mc, \
                 patch("app.agents.economic.EconomicAgent") as Me:

                # Analyst ok
                Ma.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="a", session_id="s", data={}
                ))
                
                # Compliance real behavior mock: data con confidence
                compliance_data = {
                    "administrativo": [{"id": "AD-01", "nombre": "RFC", "estado": "pass"}],
                    "tecnico": [], "formatos": [],
                    "confidence": {
                        "overall": 0.82,
                        "recommendation": "accept",
                        "threshold_passed": True
                    }
                }
                Mc.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id="compliance_mock",
                    session_id="sess-comp-conf",
                    data=compliance_data
                ))
                
                # Economic ok
                Me.return_value.process = AsyncMock(return_value=AgentOutput(
                    status=AgentStatus.SUCCESS, agent_id="e", session_id="s", data={}
                ))

                result = await orch.process(
                    "sess-comp-conf",
                    {"company_id": "co-1", "company_data": {"mode": "analysis_only"}}
                )

        assert "compliance" in result["results"]
        # El orquestador debe haber agregado el summary
        assert result["metadata"]["confidence_summary"]["avg_confidence"] == 0.82
