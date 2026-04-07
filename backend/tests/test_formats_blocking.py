import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.formats import FormatsAgent
from app.agents.mcp_context import MCPContextManager

def _memory_stub(session_state=None):
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value=session_state or {})
    mem.save_session = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem

@pytest.mark.asyncio
async def test_formats_blocking_when_slots_missing():
    """Hito 4: Verifica que FormatsAgent bloquea la generación si faltan slots críticos."""
    
    # 1. Perfil vacío (sin RFC, sin domicilio, sin representante)
    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Test S.A."
            }
        },
        "compliance_master_list": {
            "administrativo": [{"id": "1_1", "nombre": "Carta A"}]
        }
    }
    
    mem = _memory_stub(session_state={"name": "sess_4"})
    ctx = MCPContextManager(mem)
    agent = FormatsAgent(ctx)

    # 2. Ejecutar proceso
    out = await agent.process("sess_4", input_data)

    # 3. Validaciones
    assert out["status"] == "waiting_for_data"
    assert "missing" in out
    
    missing_fields = [m["field"] for m in out["missing"]]
    assert "rfc" in missing_fields
    assert "domicilio_fiscal" in missing_fields
    assert "representante_legal" in missing_fields
    
    # Verificar que se guardaron las preguntas para el chatbot
    assert mem.save_session.called
    last_save = mem.save_session.call_args[0][1]
    assert "pending_questions" in last_save
    assert len(last_save["pending_questions"]) == 3

@pytest.mark.asyncio
async def test_formats_proceeds_when_slots_poblated():
    """Hito 4: Verifica que FormatsAgent continúa si los slots ya están presentes."""
    
    input_data = {
        "company_data": {
            "master_profile": {
                "razon_social": "Test S.A.",
                "rfc": "ABC123456XYZ",
                "domicilio_fiscal": "Calle Falsa 123",
                "representante_legal": "Juan Pérez"
            }
        },
        "compliance_master_list": {
            "administrativo": [{"id": "1_1", "nombre": "Carta A"}]
        }
    }
    
    mem = _memory_stub(session_state={"name": "sess_4_ok"})
    ctx = MCPContextManager(mem)
    agent = FormatsAgent(ctx)

    # Mockear LLM para evitar llamadas reales
    agent.llm.generate = AsyncMock(return_value={"response": "Contenido Legal"})

    # Ejecutar proceso
    out = await agent.process("sess_4_ok", input_data)

    # Debe ser éxito (o al menos no ser waiting_for_data)
    assert out["status"] == "success"
    assert out["data"]["count"] == 1
