import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.agents.orchestrator import OrchestratorAgent
from app.agents.mcp_context import MCPContextManager

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
    return mem

@pytest.mark.asyncio
async def test_full_orchestrator_blocked_and_resume_flow():
    """Hito 6+: Valida el flujo real de bloqueo en el orquestador y su posterior reanudación (resume)."""
    
    # 1. Sesión Inicial
    initial_session = {
        "status": "active",
        "master_compliance_list": {"administrativo": [{"id": "A1", "nombre": "Carta"}]}
    }
    initial_company = {
        "id": "co_test",
        "master_profile": {"razon_social": "Test SA"} # Faltan rfc, domicilio, etc.
    }
    
    mem = _memory_stub(initial_session, initial_company)
    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)

    # 2. Primera corrida: debe bloquearse en 'formats' (o 'datagap' si habilitamos el guardián)
    # Mockeamos agentes para que datagap y technical pasen, pero formats bloquee
    with patch("app.agents.data_gap.DataGapAgent") as MGap, \
         patch("app.agents.technical_writer.TechnicalWriterAgent") as MTech, \
         patch("app.agents.formats.FormatsAgent") as MForm:
        
        MGap.return_value.process = AsyncMock(return_value={"status": "success"})
        MTech.return_value.process = AsyncMock(return_value={"status": "success"})
        
        # FormatsAgent bloquea porque falta RFC
        # IMPORTANTE: Como mockeamos la clase, debemos simular el efecto secundario 
        # de guardar las preguntas pendientes en la sesión de memoria.
        async def mock_form_process(sid, data):
            # Efecto secundario: guardar pregunta
            missing = [{"field": "rfc", "label": "RFC", "question": "¿Cual es?", "type": "profile"}]
            sess = await mem.get_session(sid)
            sess["pending_questions"] = missing
            sess["current_question_index"] = 0
            await mem.save_session(sid, sess)
            return {
                "status": "waiting_for_data",
                "message": "Falta RFC",
                "missing": missing
            }
        
        MForm.return_value.process = AsyncMock(side_effect=mock_form_process)

        res1 = await orch.process("sess_flow", {
            "company_id": "co_test",
            "company_data": {"mode": "generation_only"}
        })

        # Verificaciones del bloqueo
        assert res1["status"] == "waiting_for_data"
        assert res1["orchestrator_decision"]["stop_reason"] == "INCOMPLETE_FORMAT_DATA"
        
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
        
        with patch.object(chatbot.llm, "generate", AsyncMock(return_value={"response": "ABC123456XYZ"})):
            await chatbot._handle_data_intake(
                "sess_flow", "Mi RFC es ABC123456XYZ", "co_test",
                pending, 0, updated_session
            )

        # 4. Segunda corrida: Reanudar (resume_generation=True)
        # Limpiar mocks para verificar llamadas nuevas
        MGap.return_value.process.reset_mock()
        MTech.return_value.process.reset_mock()
        # Esta vez formats_agent debe tener éxito
        MForm.return_value.process = AsyncMock(return_value={"status": "success", "data": {"documentos": []}})

        # Mocks para el resto del pipeline (economic, packager, delivery)
        with patch("app.agents.economic.EconomicAgent") as MEcon, \
             patch("app.agents.economic_writer.EconomicWriterAgent") as MEconW, \
             patch("app.agents.document_packager.DocumentPackagerAgent") as MPkg, \
             patch("app.agents.delivery.DeliveryAgent") as MDel:
            
            MEcon.return_value.process = AsyncMock(return_value={"status": "success", "data": {}})
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
