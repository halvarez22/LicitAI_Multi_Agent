import os
import sys
from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ASEGURAR PATH PARA IMPORTAR app.*
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.agents.compliance_gate import ComplianceGateResult
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.agents.packager import PackResult
from app.contracts.agent_contracts import AgentOutput, AgentStatus


@pytest.fixture(autouse=True)
def _brakes_compliance_gate_ok():
    """Evita descalificación 12.1 con payloads mínimos de estos tests."""
    gate_ok = ComplianceGateResult(
        is_blocking=False,
        failed_rules=[],
        warnings=[],
        evidence={},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch("app.agents.compliance_gate.ComplianceGate") as GC, patch(
        "app.agents.packager.CompraNetPackager"
    ) as MCN:
        GC.return_value.evaluate.return_value = gate_ok
        MCN.return_value.pack.return_value = PackResult(success=True, validation_passed=True)
        yield


@pytest.fixture
def mock_ctx():
    m = MagicMock(spec=MCPContextManager)
    m.memory = MagicMock()
    
    # Estado de sesión unificado y consistente
    completed_tasks = [
        {"task": "stage_completed:analysis", "result": {"status": "success", "data": {}}},
        {"task": "stage_completed:compliance", "result": {"status": "success", "data": {}}},
        {"task": "stage_completed:economic", "result": {"status": "success", "data": {}}}
    ]
    
    session_data = {
        "id": "brake_test_sid",
        "schema_version": 1,
        "tasks_completed": completed_tasks
    }
    
    # Sincronizar ambos métodos para evitar ruidos de migración u omisión
    m.memory.get_session = AsyncMock(return_value=session_data)
    m.get_global_context = AsyncMock(return_value={
        "session_state": session_data,
        "documents_summary": []
    })
    
    m.memory.save_session = AsyncMock(return_value=True)
    m.record_task_completion = AsyncMock(return_value=True)
    m.memory.get_documents = AsyncMock(return_value=[])
    
    return m

def _generation_input() -> dict:
    return {
        "company_id": "c",
        "company_data": {"mode": "generation_only"},
        "correlation_id": "test_id",
    }


@pytest.fixture
def generation_patches():
    """Parches comunes del bloque de generación (evita efectos colaterales si se alcanza packager/delivery)."""
    return (
        patch("app.agents.data_gap.DataGapAgent.process", new_callable=AsyncMock),
        patch("app.agents.technical_writer.TechnicalWriterAgent.process", new_callable=AsyncMock),
        patch("app.agents.formats.FormatsAgent.process", new_callable=AsyncMock),
        patch("app.agents.economic_writer.EconomicWriterAgent.process", new_callable=AsyncMock),
        patch("app.agents.document_packager.DocumentPackagerAgent.process", new_callable=AsyncMock),
        patch("app.agents.delivery.DeliveryAgent.process", new_callable=AsyncMock),
    )


@pytest.mark.asyncio
async def test_orchestrator_stops_on_technical_waiting_data(mock_ctx, generation_patches):
    """Si TechnicalWriter pide datos, no deben ejecutarse formatos ni etapas posteriores."""
    orch = OrchestratorAgent(mock_ctx)
    p_gap, p_tech, p_form, p_econ, p_pack, p_del = generation_patches
    with p_gap as m_gap, p_tech as m_tech, p_form as m_form, p_econ as m_econ, p_pack as m_pack, p_del as m_del:
        m_gap.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="g", session_id="s", data={})
        m_tech.return_value = AgentOutput(
            status=AgentStatus.WAITING_FOR_DATA, agent_id="t", session_id="s", message="Falta contexto tecnico"
        )
        m_form.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="f", session_id="s", data={})
        m_econ.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="e", session_id="s", data={})
        m_pack.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="p", session_id="s", data={})
        m_del.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="d", session_id="s", data={})

        res = await orch.process("brake_test_sid", _generation_input())

    assert res["status"] == "waiting_for_data"
    assert res["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_TECHNICAL_DATA"
    assert m_form.called is False
    assert m_econ.called is False
    assert m_pack.called is False
    assert m_del.called is False


@pytest.mark.asyncio
async def test_orchestrator_stops_on_formats_waiting_data(mock_ctx, generation_patches):
    """Si Formats pide datos, no debe ejecutarse EconomicWriter ni packager/delivery."""
    orch = OrchestratorAgent(mock_ctx)
    p_gap, p_tech, p_form, p_econ, p_pack, p_del = generation_patches
    with p_gap as m_gap, p_tech as m_tech, p_form as m_form, p_econ as m_econ, p_pack as m_pack, p_del as m_del:
        m_gap.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="g", session_id="s", data={})
        m_tech.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="t", session_id="s", data={})
        m_form.return_value = AgentOutput(
            status=AgentStatus.WAITING_FOR_DATA, agent_id="f", session_id="s", message="Falta RFC"
        )
        m_econ.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="e", session_id="s", data={})
        m_pack.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="p", session_id="s", data={})
        m_del.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="d", session_id="s", data={})

        res = await orch.process("brake_test_sid", _generation_input())

    assert res["status"] == "waiting_for_data"
    assert res["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_FORMATS_DATA"
    assert m_econ.called is False
    assert m_pack.called is False
    assert m_del.called is False


@pytest.mark.asyncio
async def test_orchestrator_stops_on_economic_writer_waiting_data(mock_ctx, generation_patches):
    """Si EconomicWriter pide datos, no deben ejecutarse packager ni delivery."""
    orch = OrchestratorAgent(mock_ctx)
    p_gap, p_tech, p_form, p_econ, p_pack, p_del = generation_patches
    with p_gap as m_gap, p_tech as m_tech, p_form as m_form, p_econ as m_econ, p_pack as m_pack, p_del as m_del:
        m_gap.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="g", session_id="s", data={})
        m_tech.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="t", session_id="s", data={})
        m_form.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="f", session_id="s", data={})
        m_econ.return_value = AgentOutput(
            status=AgentStatus.WAITING_FOR_DATA, agent_id="e", session_id="s", message="Falta cotizacion"
        )
        m_pack.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="p", session_id="s", data={})
        m_del.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="d", session_id="s", data={})

        res = await orch.process("brake_test_sid", _generation_input())

    assert res["status"] == "waiting_for_data"
    assert res["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_ECONOMIC_WRITER_DATA"
    assert m_pack.called is False
    assert m_del.called is False


@pytest.mark.asyncio
async def test_orchestrator_stops_on_packager_waiting_data(mock_ctx, generation_patches):
    """Si DocumentPackager pide datos, no debe ejecutarse Delivery."""
    orch = OrchestratorAgent(mock_ctx)
    p_gap, p_tech, p_form, p_econ, p_pack, p_del = generation_patches
    with p_gap as m_gap, p_tech as m_tech, p_form as m_form, p_econ as m_econ, p_pack as m_pack, p_del as m_del:
        m_gap.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="g", session_id="s", data={})
        m_tech.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="t", session_id="s", data={})
        m_form.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="f", session_id="s", data={})
        m_econ.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="e", session_id="s", data={})
        m_pack.return_value = AgentOutput(
            status=AgentStatus.WAITING_FOR_DATA, agent_id="p", session_id="s", message="Falta ruta de salida"
        )
        m_del.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="d", session_id="s", data={})

        res = await orch.process("brake_test_sid", _generation_input())

    assert res["status"] == "waiting_for_data"
    assert res["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_PACKAGER_DATA"
    assert m_pack.called is True
    assert m_del.called is False


@pytest.mark.asyncio
async def test_orchestrator_stops_on_delivery_waiting_data(mock_ctx, generation_patches):
    """Si Delivery pide datos, el orquestador devuelve waiting_for_data (ultima etapa del bucle)."""
    orch = OrchestratorAgent(mock_ctx)
    p_gap, p_tech, p_form, p_econ, p_pack, p_del = generation_patches
    with p_gap as m_gap, p_tech as m_tech, p_form as m_form, p_econ as m_econ, p_pack as m_pack, p_del as m_del:
        m_gap.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="g", session_id="s", data={})
        m_tech.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="t", session_id="s", data={})
        m_form.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="f", session_id="s", data={})
        m_econ.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="e", session_id="s", data={})
        m_pack.return_value = AgentOutput(status=AgentStatus.SUCCESS, agent_id="p", session_id="s", data={})
        m_del.return_value = AgentOutput(
            status=AgentStatus.WAITING_FOR_DATA, agent_id="d", session_id="s", message="Falta confirmacion de entrega"
        )

        res = await orch.process("brake_test_sid", _generation_input())

    assert res["status"] == "waiting_for_data"
    assert res["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_DELIVERY_DATA"
    assert m_pack.called is True
    assert m_del.called is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
