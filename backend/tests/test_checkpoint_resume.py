from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, patch

from app.agents.compliance_gate import ComplianceGateResult
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.agents.packager import PackResult

# Hitos previos ya persistidos: evita Analyst/Compliance reales en generation_only (CI sin Chroma).
_PRE_GEN_TASKS = [
    {"task": "stage_completed:analysis", "result": {"status": "success", "data": {}}},
    {"task": "stage_completed:compliance", "result": {"status": "success", "data": {"data": {}}}},
    {"task": "stage_completed:economic", "result": {"status": "success", "data": {}}},
]


def _compliance_gate_ok() -> ComplianceGateResult:
    return ComplianceGateResult(
        is_blocking=False,
        failed_rules=[],
        warnings=[],
        evidence={},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _memory_stub(session_state=None):
    mem = AsyncMock()
    # Simular recuperación de sesión
    mem.get_session = AsyncMock(return_value=session_state or {})
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem

@pytest.mark.asyncio
async def test_checkpoint_resume_skip_done_jobs():
    """Hito 3: Verifica que el orquestador no repita agentes marcados como 'done'."""
    
    # 1. Estado inicial con 'technical' ya completado
    initial_state = {
        "tasks_completed": list(_PRE_GEN_TASKS),
        "generation_state": {
            "status": "running",
            "jobs": [
                {"id": "datagap", "type": "checkpoint", "status": "done"},
                {"id": "technical", "type": "agent", "status": "done"},
                {"id": "formats", "type": "agent", "status": "pending"},
                {"id": "economic_writer", "type": "agent", "status": "pending"},
                {"id": "packager", "type": "agent", "status": "pending"},
                {"id": "delivery", "type": "agent", "status": "pending"}
            ]
        }
    }
    
    mem = _memory_stub(session_state=initial_state)
    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)

    # 2. Mockear todos los agentes (+ gate 12.1 y CompraNet para datos mínimos de sesión)
    with patch("app.agents.compliance_gate.ComplianceGate") as MGate, \
         patch("app.agents.packager.CompraNetPackager") as MCN, \
         patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech, \
         patch("app.agents.formats.FormatsAgent") as MForm, \
         patch("app.agents.economic_writer.EconomicWriterAgent") as MEcon, \
         patch("app.agents.document_packager.DocumentPackagerAgent") as MPkg, \
         patch("app.agents.delivery.DeliveryAgent") as MDel:

        MGate.return_value.evaluate.return_value = _compliance_gate_ok()
        MCN.return_value.pack.return_value = PackResult(success=True, validation_passed=True)
        
        # Seteamos retornos exitosos para los que se ejecuten
        MForm.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
        MEcon.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
        MPkg.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
        MDel.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})

        # 3. Ejecutar con resume_generation=True
        out = await orch.process("sess_test", {
            "company_id": "co_1",
            "company_data": {"mode": "generation_only"},
            "resume_generation": True
        })

        # 4. Validaciones
        assert out["status"] == "success"
        
        # Agentes que NO debieron llamarse (ya estaban done)
        MGap.assert_not_called()
        MTech.assert_not_called()
        
        # Agentes que SÍ debieron llamarse
        MForm.return_value.process.assert_called()
        MEcon.return_value.process.assert_called()
        
        # Verificar que el estado final de la sesión se actualizó a completed
        # Buscamos la última llamada a save_session
        last_save = mem.save_session.call_args[0][1]
        assert last_save["generation_state"]["status"] == "completed"
        # Verificar que job 'formats' ahora está done
        formats_job = next(j for j in last_save["generation_state"]["jobs"] if j["id"] == "formats")
        assert formats_job["status"] == "done"

@pytest.mark.asyncio
async def test_checkpoint_full_reset_without_resume_flag():
    """Hito 3: Verifica que sin el flag resume, se reinicia la cola aunque existiera estado previo."""
    
    # Estado previo donde todo estaba hecho
    old_state = {
        "tasks_completed": list(_PRE_GEN_TASKS),
        "generation_state": {
            "status": "completed",
            "jobs": [{"id": j, "status": "done"} for j in ["datagap", "technical", "formats", "economic_writer", "packager", "delivery"]]
        }
    }
    
    mem = _memory_stub(session_state=old_state)
    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)

    with patch("app.agents.compliance_gate.ComplianceGate") as MGate, \
         patch("app.agents.packager.CompraNetPackager") as MCN, \
         patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech:

        MGate.return_value.evaluate.return_value = _compliance_gate_ok()
        MCN.return_value.pack.return_value = PackResult(success=True, validation_passed=True)
        MGap.return_value.process = AsyncMock(return_value={"status": "success"})
        MTech.return_value.process = AsyncMock(return_value={"status": "success"})

        # Ejecutar SIN resume_generation (o False)
        await orch.process("sess_reset", {
            "company_id": "co_1",
            "company_data": {"mode": "generation_only"},
            "resume_generation": False
        })

        # Debieron llamarse a pesar del estado previo 'done'
        MGap.assert_called()
        MTech.assert_called()
