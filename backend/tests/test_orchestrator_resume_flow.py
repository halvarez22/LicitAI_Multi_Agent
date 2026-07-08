from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.compliance_gate import ComplianceGateResult
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager
from app.agents.packager import PackResult
from app.contracts.agent_contracts import AgentOutput, AgentStatus
from app.services.resilient_llm import LLMResponse

def _memory_stub(session=None, company=None):
    mem = AsyncMock()
    # Usamos una variable local para mantener el estado entre llamadas simuladas
    state = {"session": session or {}, "company": company or {}}
    
    async def get_sess(sid): return state["session"]
    async def save_sess(sid, data): 
        state["session"].update(data)
        return True
    async def get_co(cid): return state["company"]
    async def save_co(cid, data):
        state["company"].update(data)
        return True

    mem.get_session = AsyncMock(side_effect=get_sess)
    mem.save_session = AsyncMock(side_effect=save_sess)
    mem.get_company = AsyncMock(side_effect=get_co)
    mem.save_company = AsyncMock(side_effect=save_co)
    mem.get_conversation = AsyncMock(return_value=[])
    mem.save_conversation = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    return mem

@pytest.mark.asyncio
async def test_full_orchestrator_blocked_and_resume_flow():
    """Hito 6+: Valida el flujo real de bloqueo en el orquestador y su posterior reanudación (resume)."""
    
    # 1. Sesión Inicial (análisis/compliance/económico ya persistidos → ir directo a generación)
    initial_session = {
        "status": "active",
        "master_compliance_list": {"administrativo": [{"id": "A1", "nombre": "Carta"}]},
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {"status": "success", "data": {}}},
            {
                "task": "stage_completed:compliance",
                "result": {
                    "status": "success",
                    "data": {
                        "data": {"administrativo": [{"id": "A1", "nombre": "Carta"}]}
                    },
                },
            },
            {"task": "stage_completed:economic", "result": {"status": "success", "data": {}}},
            {
                "task": "economic_proposal",
                "result": {
                    "status": "complete",
                    "total_base": 10.0,
                    "items": [{"concepto": "Servicio", "cantidad": 1, "precio_unitario": 10, "subtotal": 10}],
                },
            },
        ],
    }
    initial_company = {
        "id": "co_test",
        "master_profile": {"razon_social": "Test SA"} # Faltan rfc, domicilio, etc.
    }
    
    mem = _memory_stub(initial_session, initial_company)
    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)

    gate_ok = ComplianceGateResult(
        is_blocking=False,
        failed_rules=[],
        warnings=[],
        evidence={},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # 2. Primera corrida: debe bloquearse en 'formats' (o 'datagap' si habilitamos el guardián)
    # Mockeamos agentes para que datagap y technical pasen, pero formats bloquee
    with patch("app.agents.compliance_gate.ComplianceGate") as MGate, \
         patch("app.agents.packager.CompraNetPackager") as MCN, \
         patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech, \
         patch("app.agents.formats.FormatsAgent") as MForm:

        MGate.return_value.evaluate.return_value = gate_ok
        MCN.return_value.pack.return_value = PackResult(success=True, validation_passed=True)
        MGap.return_value.process = AsyncMock(return_value={"status": "success"})
        MTech.return_value.process = AsyncMock(return_value={"status": "success"})
        
        # FormatsAgent bloquea porque falta RFC
        # IMPORTANTE: Como mockeamos la clase, debemos simular el efecto secundario 
        # de guardar las preguntas pendientes en la sesión de memoria.
        async def mock_form_process(agent_input):
            sid = agent_input.session_id
            missing = [{"field": "rfc", "label": "RFC", "question": "¿Cual es?", "type": "profile"}]
            sess = await mem.get_session(sid)
            sess["pending_questions"] = missing
            sess["current_question_index"] = 0
            await mem.save_session(sid, sess)
            return AgentOutput(
                status=AgentStatus.WAITING_FOR_DATA,
                agent_id="formats_test",
                session_id=sid,
                message="Falta RFC",
                data={"missing": missing},
            )
        
        MForm.return_value.process = AsyncMock(side_effect=mock_form_process)

        res1 = await orch.process("sess_flow", {
            "company_id": "co_test",
            "company_data": {"mode": "generation_only"},
            "resume_generation": True,
        })

        # Verificaciones del bloqueo
        assert res1["status"] == "waiting_for_data"
        assert res1["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_FORMATS_DATA"
        
        # El job de formatos debe estar blocked
        gen_state = res1["generation_state"]
        job_formats = next(j for j in gen_state["jobs"] if j["id"] == "formats")
        assert job_formats["status"] == "blocked"
        
        # Technical debe estar DONE
        job_tech = next(j for j in gen_state["jobs"] if j["id"] == "technical")
        assert job_tech["status"] == "done"

        # 3. Simular que el usuario proporciona el dato (RFC)
        from app.agents.chatbot_rag import ChatbotRAGAgent
        chatbot = ChatbotRAGAgent(ctx)
        
        # Recuperamos las preguntas que el formats agent guardó en la sesión
        updated_session = await mem.get_session("sess_flow")
        pending = updated_session.get("pending_questions", [])
        
        with patch.object(
            chatbot.llm,
            "generate",
            AsyncMock(
                return_value=LLMResponse(success=True, response="ABC123456XYZ")
            ),
        ):
            await chatbot._handle_data_intake(
                "sess_flow", "Mi RFC es ABC123456XYZ", "co_test",
                pending, 0, updated_session
            )

        # 4. Segunda corrida: Reanudar (resume_generation=True)
        # Limpiar mocks para verificar llamadas nuevas
        MGap.return_value.process.reset_mock()
        MTech.return_value.process.reset_mock()
        # Esta vez formats_agent debe tener éxito
        async def _formats_ok(agent_input):
            return AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="formats_test",
                session_id=agent_input.session_id,
                data={"documentos": []},
            )

        MForm.return_value.process = AsyncMock(side_effect=_formats_ok)

        # Mocks para el resto del pipeline (economic, packager, delivery)
        with patch("app.agents.economic.EconomicAgent") as MEcon, \
             patch("app.agents.economic_writer.EconomicWriterAgent") as MEconW, \
             patch("app.agents.document_packager.DocumentPackagerAgent") as MPkg, \
             patch("app.agents.delivery.DeliveryAgent") as MDel:
            
            MEcon.return_value.process = AsyncMock(
                return_value=AgentOutput(
                    status=AgentStatus.SUCCESS,
                    agent_id="economic_test",
                    session_id="sess_flow",
                    data={"items": [{"concepto": "Servicio", "cantidad": 1, "precio_unitario": 10, "subtotal": 10}], "total_base": 10, "grand_total": 11.6},
                )
            )
            MEconW.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
            MPkg.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
            MDel.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
            
            res2 = await orch.process("sess_flow", {
                "company_id": "co_test",
                "company_data": {"mode": "generation_only"},
                "resume_generation": True # CRITICAL
            })

            # Verificaciones de la reanudación
            assert res2["status"] == "success"
            
            # Agentes DONE no deben llamarse de nuevo
            MGap.return_value.process.assert_not_called()
            MTech.return_value.process.assert_not_called()
            
            # Formats sí debe llamarse (estaba blocked)
            MForm.return_value.process.assert_called_once()
            
            # El estado final debe ser completed
            assert res2["generation_state"]["status"] == "completed"
            final_session = await mem.get_session("sess_flow")
            assert final_session.get("pending_questions") == []
            assert final_session.get("current_question_index") == 0


@pytest.mark.asyncio
async def test_generation_final_ok_clears_pending_and_unblocks_economic_writer_with_docs():
    initial_session = {
        "status": "active",
        "pending_questions": [{"field": "stale", "question_type": "B"}],
        "current_question_index": 0,
        "master_compliance_list": {"administrativo": [{"id": "A1", "nombre": "Carta"}]},
        "tasks_completed": [
            {"task": "stage_completed:analysis", "result": {"status": "success", "data": {}}},
            {
                "task": "stage_completed:compliance",
                "result": {"status": "success", "data": {"data": {"administrativo": [{"id": "A1", "nombre": "Carta"}]}}},
            },
            {
                "task": "economic_proposal",
                "result": {
                    "status": "complete",
                    "total_base": 10.0,
                    "items": [{"concepto": "Servicio", "cantidad": 1, "precio_unitario": 10, "subtotal": 10}],
                    "grand_total": 11.6,
                },
            },
            {"task": "stage_completed:economic", "result": {"status": "success", "data": {}}},
        ],
    }
    mem = _memory_stub(initial_session, {"id": "co_test", "master_profile": {"razon_social": "Test SA", "rfc": "ABC010101AAA"}})
    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)

    gate_ok = ComplianceGateResult(
        is_blocking=False,
        failed_rules=[],
        warnings=[],
        evidence={},
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    econ_waiting_with_docs = AgentOutput(
        status=AgentStatus.WAITING_FOR_DATA,
        agent_id="economic_writer",
        session_id="sess-final-ok",
        message="Advertencia económica no bloqueante",
        data={
            "documentos": [
                {"nombre": "Catálogo Económico", "ruta": "/tmp/cat.xlsx", "status": "FINAL", "tipo": "tabla_precios"}
            ]
        },
    )

    success_output = lambda agent_id: AgentOutput(
        status=AgentStatus.SUCCESS,
        agent_id=agent_id,
        session_id="sess-final-ok",
        data={"documentos": []},
    )

    with patch("app.agents.compliance_gate.ComplianceGate") as MGate, \
         patch("app.agents.packager.CompraNetPackager") as MCN, \
         patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech, \
         patch("app.agents.formats.FormatsAgent") as MForm, \
         patch("app.agents.economic_writer.EconomicWriterAgent") as MEconW, \
         patch("app.agents.document_packager.DocumentPackagerAgent") as MPkg, \
         patch("app.agents.delivery.DeliveryAgent") as MDel, \
         patch.object(OrchestratorAgent, "_generate_checklist", AsyncMock(return_value=[])):
        MGate.return_value.evaluate.return_value = gate_ok
        MCN.return_value.pack.return_value = PackResult(success=True, validation_passed=True)
        MGap.return_value.process = AsyncMock(return_value={"status": "success"})
        MTech.return_value.process = AsyncMock(return_value=success_output("technical"))
        MForm.return_value.process = AsyncMock(return_value=success_output("formats"))
        MEconW.return_value.process = AsyncMock(return_value=econ_waiting_with_docs)
        MPkg.return_value.process = AsyncMock(return_value=success_output("packager"))
        MDel.return_value.process = AsyncMock(return_value=success_output("delivery"))

        out = await orch.process(
            "sess-final-ok",
            {"company_id": "co_test", "company_data": {"mode": "generation_only"}, "resume_generation": True},
        )

    assert out["orchestrator_decision"]["stop_reason"] == "FINAL_OK"
    assert out["status"] == "success"
    econ_job = next(j for j in out["generation_state"]["jobs"] if j["id"] == "economic_writer")
    assert econ_job["status"] == "done"
    final_session = await mem.get_session("sess-final-ok")
    assert final_session.get("pending_questions") == []
    assert final_session.get("current_question_index") == 0


def test_apply_filtered_compliance_master_list_strips_causales():
    from app.agents.orchestrator import _apply_filtered_compliance_master_list
    from app.contracts.agent_contracts import AgentInput

    raw = {
        "administrativo": [
            {
                "id": "AD-1",
                "nombre": "Acta constitutiva",
                "descripcion": "Legal",
                "snippet": "Acta",
                "tipo_accion": "presentar_fisico",
            },
            {
                "id": "AD-2",
                "nombre": "No presentar documentación engrapada",
                "descripcion": "Causal",
                "snippet": "No presentar",
                "tipo_accion": "generar",
            },
        ],
        "tecnico": [],
        "formatos": [],
    }
    agent_input = AgentInput(session_id="s1", company_data={})
    input_data = {"compliance_master_list": raw}
    out_data, out_agent = _apply_filtered_compliance_master_list(input_data, agent_input)
    names = [x["nombre"] for x in out_data["compliance_master_list"]["administrativo"]]
    # presentar_fisico y causales no entran a la cola de generación
    assert names == []
    assert out_data["compliance_master_list"]["tecnico"] == []
    meta = out_data.get("generation_filter_meta") or {}
    assert meta.get("skipped_action", 0) >= 1
