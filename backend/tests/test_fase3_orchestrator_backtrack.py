"""
tests/test_fase3_orchestrator_backtrack.py
Pruebas de integración del orquestador con el bucle de backtracking activo.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentOutput, AgentStatus
from app.config.settings import settings


@pytest.mark.asyncio
async def test_orchestrator_reruns_compliance_once_on_conflict():
    with patch.object(settings, "BACKTRACKING_ENABLED", True), \
         patch.object(settings, "BACKTRACK_MAX_ITERATIONS", 2), \
         patch.object(settings, "REDIS_HOST", "localhost"), \
         patch("app.agents.mcp_context.MCPContextManager") as mock_cm, \
         patch("redis.Redis") as mock_redis, \
         patch("app.agents.analyst.AnalystAgent") as Ma, \
         patch("app.agents.compliance.ComplianceAgent") as Mc:
        
        mock_cm_instance = mock_cm.return_value
        mock_cm_instance.memory.get_session = AsyncMock(return_value={"status": "running"})
        mock_cm_instance.get_global_context = AsyncMock(return_value={"tasks_completed": []})
        mock_cm_instance.memory.save_session = AsyncMock(return_value=True)
        mock_cm_instance.record_task_completion = AsyncMock(return_value=True)

        Ma.return_value.process = AsyncMock(return_value=AgentOutput(
            status=AgentStatus.SUCCESS, agent_id="analyst", session_id="s1",
            data={"requirements": [{"id": "REQ-CONF-1"}]}
        ))
        
        res1 = AgentOutput(status=AgentStatus.SUCCESS, agent_id="c", session_id="s1", data={"administrativo": [{"id": "FAKE_TO_FORCE_BACKTRACK", "estado": "pass"}]})
        res2 = AgentOutput(status=AgentStatus.SUCCESS, agent_id="c", session_id="s1", data={"administrativo": [{"id": "REQ-CONF-1", "estado": "pass"}]})
        Mc.return_value.process = AsyncMock(side_effect=[res1, res2])
        
        orch = OrchestratorAgent(mock_cm_instance)
        result = await orch.process("s1", {"company_id": "c1", "company_data": {"mode": "analysis_only"}})
        
        assert Mc.return_value.process.call_count == 2
        assert result["metadata"]["backtracking"]["iterations"] == 1

@pytest.mark.asyncio
async def test_orchestrator_skips_backtrack_if_flag_off():
    with patch.object(settings, "BACKTRACKING_ENABLED", False), \
         patch("app.agents.mcp_context.MCPContextManager") as mock_cm, \
         patch("app.agents.analyst.AnalystAgent") as Ma, \
         patch("app.agents.compliance.ComplianceAgent") as Mc:
        
        mock_cm_instance = mock_cm.return_value
        mock_cm_instance.memory.get_session = AsyncMock(return_value={"status": "running"})
        mock_cm_instance.get_global_context = AsyncMock(return_value={"tasks_completed": []})
        mock_cm_instance.memory.save_session = AsyncMock(return_value=True)
        mock_cm_instance.record_task_completion = AsyncMock(return_value=True)

        Ma.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="a", session_id="s1", data={"requirements": [{"id": "X"}]}))
        Mc.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="c", session_id="s1", data={"administrativo": [{"id": "X", "estado": "pass"}]}))
        
        orch = OrchestratorAgent(mock_cm_instance)
        result = await orch.process("s1", {"company_id": "c1", "company_data": {"mode": "analysis_only"}})
        
        assert Ma.return_value.process.call_count == 1
        assert Mc.return_value.process.call_count == 1
        assert result["metadata"].get("backtracking") is None
