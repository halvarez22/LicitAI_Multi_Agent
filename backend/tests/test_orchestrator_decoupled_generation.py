"""
Tests de integración F2: desacople técnico/económico en orquestador.

CA-1.1: generation_economic no ejecuta TechnicalWriter.
CA-1.2: generation_technical no bloquea por snapshot económico incompleto.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.compliance_gate import ComplianceGateResult
from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.contracts.agent_contracts import AgentOutput, AgentStatus


def _memory_stub(session=None, company=None):
    mem = AsyncMock()
    state = {"session": session or {}, "company": company or {}}

    async def get_sess(_sid):
        return state["session"]

    async def save_sess(_sid, data):
        state["session"].update(data)
        return True

    async def get_co(_cid):
        return state["company"]

    mem.get_session = AsyncMock(side_effect=get_sess)
    mem.save_session = AsyncMock(side_effect=save_sess)
    mem.get_company = AsyncMock(side_effect=get_co)
    mem.get_conversation = AsyncMock(return_value=[])
    mem.save_conversation = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    return mem


def _analysis_ready_session(*, economic_snapshot=None):
    tasks = [
        {"task": "stage_completed:analysis", "result": {"status": "success", "data": {}}},
        {
            "task": "stage_completed:compliance",
            "result": {
                "status": "success",
                "data": {"data": {"administrativo": [{"id": "A1", "nombre": "Carta"}]}},
            },
        },
        {"task": "stage_completed:economic", "result": {"status": "success", "data": {}}},
    ]
    if economic_snapshot is not None:
        tasks.append({"task": "economic_proposal", "result": economic_snapshot})
    session = {
        "status": "active",
        "company_id": "co_test",
        "master_profile": {"razon_social": "Test SA", "rfc": "XAXX010101000"},
        "master_compliance_list": {"administrativo": [{"id": "A1", "nombre": "Carta"}]},
        "tasks_completed": tasks,
        "triage_context": {"tender_category": "servicios", "law": "LFPC"},
    }
    if economic_snapshot is not None:
        if economic_snapshot.get("status") == "complete":
            session["capture_matrix_blocks"] = [
                {"matrix_rows": [{"field": "p1", "label": "Concepto"}]}
            ]
            session["economic_user_inputs"] = {
                "p1": float(economic_snapshot.get("total_base") or 1.0)
            }
            session["pending_questions"] = []
    return session


def _gate_ok():
    return ComplianceGateResult(
        is_blocking=False,
        failed_rules=[],
        warnings=[],
        evidence={},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@pytest.mark.asyncio
async def test_technical_mode_runs_without_economic_snapshot(monkeypatch):
    """CA-1.2: precios incompletos no bloquean generation_technical."""
    monkeypatch.setattr(
        "app.services.generation_queue_controller.dual_stream_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.services.generation_concurrency_controller.dual_stream_enabled",
        lambda: False,
    )
    session = _analysis_ready_session(economic_snapshot={"status": "incomplete", "total_base": 0, "items": []})
    mem = _memory_stub(session, {"id": "co_test", "master_profile": {"razon_social": "Test SA", "rfc": "XAXX010101000"}})
    orch = OrchestratorAgent(MCPContextManager(mem))

    tech_out = AgentOutput(
        status=AgentStatus.SUCCESS,
        agent_id="technical_writer",
        session_id="sess_tech",
        data={"documentos": [{"nombre": "propuesta.docx"}]},
    )
    fmt_out = AgentOutput(
        status=AgentStatus.SUCCESS,
        agent_id="formats",
        session_id="sess_tech",
        data={"documentos": [{"nombre": "carta.docx"}]},
    )

    with patch("app.agents.compliance_gate.ComplianceGate") as MGate, \
         patch("app.agents.packager.CompraNetPackager") as MCN, \
         patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech, \
         patch("app.agents.formats.FormatsAgent") as MFmt, \
         patch("app.agents.economic_writer.EconomicWriterAgent") as MEco, \
         patch("app.agents.document_packager.DocumentPackagerAgent") as MPkg, \
         patch("app.agents.delivery.DeliveryAgent") as MDel, \
         patch("app.agents.orchestrator._ensure_economic_snapshot_ready", new_callable=AsyncMock) as MEnsure, \
         patch("app.services.generated_outputs_cleanup.wipe_session_output_disk_only", new_callable=AsyncMock) as MWipe:

        MGate.return_value.evaluate.return_value = _gate_ok()
        MCN.return_value.pack.return_value = MagicMock(success=True, validation_passed=True)
        MGap.return_value.process = AsyncMock(
            return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="datagap", session_id="sess_tech", data={})
        )
        MTech.return_value.process = AsyncMock(return_value=tech_out)
        MFmt.return_value.process = AsyncMock(return_value=fmt_out)
        MEco.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="eco", session_id="sess_tech", data={}))
        MPkg.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="pkg", session_id="sess_tech", data={}))
        MDel.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="del", session_id="sess_tech", data={}))
        MEnsure.return_value = (False, {"status": "waiting_for_data", "message": "faltan precios"})
        MWipe.return_value = {"removed_count": 0, "preserved_subdirs": []}

        out = await orch.process(
            session_id="sess_tech",
            input_data={
                "company_id": "co_test",
                "company_data": {"mode": "generation_only", "generation_mode": "technical"},
                "generation_mode": "technical",
                "resume_generation": False,
            },
        )

        MTech.return_value.process.assert_awaited()
        MFmt.return_value.process.assert_awaited()
        MEco.return_value.process.assert_not_awaited()
        MEnsure.assert_not_awaited()
        jobs = {j["id"]: j["status"] for j in out.get("generation_state", {}).get("jobs", [])}
        assert jobs.get("economic_writer") == "skipped"
        assert jobs.get("technical") in ("done", "pending", "running") or out.get("status") != "waiting_for_data"


@pytest.mark.asyncio
async def test_economic_mode_skips_technical_writer():
    """CA-1.1: generation_economic no invoca TechnicalWriterAgent."""
    snapshot = {
        "status": "complete",
        "total_base": 1000.0,
        "items": [{"concept_key": "p1", "unit_price": 1000.0}],
    }
    session = _analysis_ready_session(economic_snapshot=snapshot)
    mem = _memory_stub(session, {"id": "co_test", "master_profile": {"razon_social": "Test SA", "rfc": "XAXX010101000"}})
    orch = OrchestratorAgent(MCPContextManager(mem))

    eco_out = AgentOutput(
        status=AgentStatus.SUCCESS,
        agent_id="economic_writer",
        session_id="sess_eco",
        data={"documentos": [{"nombre": "anexo.xlsx"}]},
    )

    with patch("app.agents.compliance_gate.ComplianceGate") as MGate, \
         patch("app.agents.packager.CompraNetPackager") as MCN, \
         patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech, \
         patch("app.agents.formats.FormatsAgent") as MFmt, \
         patch("app.agents.economic_writer.EconomicWriterAgent") as MEco, \
         patch("app.agents.document_packager.DocumentPackagerAgent") as MPkg, \
         patch("app.agents.delivery.DeliveryAgent") as MDel, \
         patch("app.agents.orchestrator._ensure_economic_snapshot_ready", new_callable=AsyncMock) as MEnsure, \
         patch("app.services.generated_outputs_cleanup.wipe_session_output_disk_only", new_callable=AsyncMock) as MWipe:

        MGate.return_value.evaluate.return_value = _gate_ok()
        MCN.return_value.pack.return_value = MagicMock(success=True, validation_passed=True)
        MGap.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="dg", session_id="sess_eco", data={}))
        MTech.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="tw", session_id="sess_eco", data={}))
        MFmt.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="fm", session_id="sess_eco", data={}))
        MEco.return_value.process = AsyncMock(return_value=eco_out)
        MPkg.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="pkg", session_id="sess_eco", data={}))
        MDel.return_value.process = AsyncMock(return_value=AgentOutput(status=AgentStatus.SUCCESS, agent_id="del", session_id="sess_eco", data={}))
        MEnsure.return_value = (True, None)
        MWipe.return_value = {"removed_count": 0, "preserved_subdirs": []}

        out = await orch.process(
            session_id="sess_eco",
            input_data={
                "company_id": "co_test",
                "company_data": {"mode": "generation_only", "generation_mode": "economic"},
                "generation_mode": "economic",
                "resume_generation": False,
            },
        )

        MTech.return_value.process.assert_not_awaited()
        MFmt.return_value.process.assert_not_awaited()
        MGap.return_value.process.assert_not_awaited()
        MEco.return_value.process.assert_awaited()
        jobs = {j["id"]: j["status"] for j in out.get("generation_state", {}).get("jobs", [])}
        assert jobs.get("technical") == "skipped"
        assert jobs.get("datagap") == "skipped"
