import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agents.economic_writer import EconomicWriterAgent
from app.agents.mcp_context import MCPContextManager

def _memory_stub(session: dict | None = None):
    mem = AsyncMock()
    sess = session if session is not None else {"tasks_completed": []}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    return mem

@pytest.mark.asyncio
async def test_writer_consume_input_data_sin_llamar_llm(tmp_path):
    """Prueba que consuma datos inyectados de Fase 1 sin usar LLM y cree un dict "success"."""
    ctx = MCPContextManager(_memory_stub())
    writer = EconomicWriterAgent(ctx)
    
    # Mocking self._generate_price_excel and self._generate_anexo_ae and carta_compromiso
    writer._generate_price_excel = MagicMock(return_value={"total": 100})
    writer._generate_anexo_ae = MagicMock()
    writer._generate_carta_compromiso = MagicMock()
    
    input_data = {
        "company_id": "c1",
        "company_data": {"master_profile": {"razon_social": "Test Inc"}},
        "results": {
            "economic": {
                "data": {
                    "items": [
                        {"concepto": "Servicio X", "cantidad": 1, "precio_unitario": 50, "subtotal": 50}
                    ],
                    "total_base": 50,
                    "grand_total": 58
                }
            }
        }
    }
    
    with patch("os.makedirs"):
        out = await writer.process("sess_test_1", input_data)
        
    assert out["status"] == "success"
    assert "data" in out
    assert out["data"]["resumen_economico"]["total"] == 58
    assert not hasattr(writer, 'llm')


@pytest.mark.asyncio
async def test_writer_falla_si_no_hay_datos_economicos():
    """Valida que falle con error en lugar de trabarse en el catálogo vacío."""
    ctx = MCPContextManager(_memory_stub())
    writer = EconomicWriterAgent(ctx)
    
    input_data = {
        "company_id": "c2",
        "company_data": {"master_profile": {}},
        # Sin key "results"
    }
    
    out = await writer.process("sess_test_err", input_data)
    
    assert out["status"] == "error"
    assert "No se encontró" in out["message"]
