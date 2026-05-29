import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agents.economic_writer import EconomicWriterAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus

def _memory_stub(session: dict | None = None):
    mem = AsyncMock()
    sess = session if session is not None else {"tasks_completed": []}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
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
    
    inp = AgentInput(
        session_id="sess_test_1",
        company_id="c1",
        company_data={
            "master_profile": {
                "razon_social": "Test Inc",
                "rfc": "TST010101AAA",
                "representante_legal": "Ana Test",
            },
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
    )
    
    with patch("os.makedirs"):
        out = await writer.process(inp)
    
    if out.status == AgentStatus.ERROR:
        print(f"ERROR DETAIL: {out.error}")
        
    assert out.status == AgentStatus.SUCCESS
    assert out.data["resumen_economico"]["total"] == 58
    assert "materialization_metrics" in out.data


@pytest.mark.asyncio
async def test_writer_falla_si_no_hay_datos_economicos():
    """Valida que falle con error en lugar de trabarse en el catálogo vacío."""
    ctx = MCPContextManager(_memory_stub())
    writer = EconomicWriterAgent(ctx)
    
    inp = AgentInput(
        session_id="sess_test_err",
        company_id="c2",
        company_data={"master_profile": {}}
    )
    
    out = await writer.process(inp)
    
    assert out.status == AgentStatus.ERROR
    assert "No se encontró" in out.error


@pytest.mark.asyncio
async def test_writer_waiting_cuando_subtotal_cero_sin_ack():
    """Defensa en profundidad: no materializar paquete económico vacío de negocio."""
    ctx = MCPContextManager(_memory_stub())
    writer = EconomicWriterAgent(ctx)
    writer._generate_price_excel = MagicMock()
    writer._generate_anexo_ae = MagicMock()
    writer._generate_carta_compromiso = MagicMock()
    inp = AgentInput(
        session_id="sess_zero_subtotal",
        company_id="c1",
        company_data={
            "master_profile": {"razon_social": "Test Inc"},
            "economic_data": {
                "items": [
                    {
                        "concepto": "Supervisor General (Sin costo)",
                        "cantidad": 1,
                        "precio_unitario": 0.0,
                        "subtotal": 0.0,
                    }
                ],
                "total_base": 0.0,
                "grand_total": 0.0,
                "allow_zero_total_base_ack": False,
            },
        },
    )
    out = await writer.process(inp)
    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert out.message and "subtotal" in out.message.lower()


@pytest.mark.asyncio
async def test_writer_bloqueo_validacion_sin_items_retorna_waiting_no_error():
    """Pausa esperada (validación / pendientes) no debe mapearse a ERROR de sistema."""
    sess = {
        "tasks_completed": [
            {
                "task": "economic_proposal",
                "result": {
                    "status": "waiting_for_data",
                    "items": [],
                    "validation_result": {"blocking_issues": ["precios_positivos: ejemplo"]},
                    "missing": [
                        {"field": "validation_rule_1", "type": "economic_validation_blocking"}
                    ],
                },
            }
        ]
    }
    ctx = MCPContextManager(_memory_stub(session=sess))
    writer = EconomicWriterAgent(ctx)
    inp = AgentInput(session_id="sess_waiting_writer", company_id="c2", company_data={"master_profile": {}})
    out = await writer.process(inp)
    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert out.message and "validaciones pendientes" in out.message.lower()
