"""
Integration tests for enhanced extraction pipeline.

Validates: Requirements 15.2, 15.3, 15.4, 15.5, 16.1, 16.2, 17.1, 17.2, 18.1, 18.2, 18.3, 18.4
"""
import json
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput
from app.config.settings import settings


def _agent_input(session_id: str) -> AgentInput:
    return AgentInput(session_id=session_id, mode="analysis_only")


def _llm_ok(response_str: str) -> SimpleNamespace:
    return SimpleNamespace(success=True, response=response_str, error=None)


def _memory_stub():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={"tasks_completed": []})
    mem.save_session = AsyncMock(return_value=True)
    mem.save_agent_state = AsyncMock(return_value=True)
    mem.get_agent_state = AsyncMock(return_value=None)
    mem.get_documents = AsyncMock(return_value=[])
    mem.get_line_items_for_session = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


_SETTINGS_ON = dict(
    ENHANCED_EXTRACTION_ENABLED=True,
    EXPERIENCE_LAYER_ENABLED=False,
    CONFIDENCE_ENABLED=False,
)

# ---------------------------------------------------------------------------
# 10.1 Test Fixtures (OCR Text and JSON responses)
# ---------------------------------------------------------------------------

SAMPLE_OCR_SOLVENCIA = """
Deberá presentar evidencia de experiencia mínima de 5 años.
Es requisito contar con 3 contratos previos similares.
El personal clave deberá contar con título profesional de ingeniería.
Se valorará positivamente contar con certificación ISO 9001 vigente.
"""

SAMPLE_OCR_CONTRACTUAL = """
El tipo de contrato será abierto con base en precios unitarios.
En caso de atraso, se aplicará una penalización del 1% por cada día de retraso.
El proveedor entregará una garantía de cumplimiento por el 10% del monto total.
"""

def generate_mock_side_effect(enhanced_response: str):
    """Factory for LLM generate mock that handles both calls."""
    async def mock_generate(*args, **kwargs):
        prompt = kwargs.get("prompt", "")
        # First call: Main extraction (detect by "criterios_evaluacion" or "SECCIÓN ECONÓMICA")
        if "criterios_evaluacion" in prompt:
            return _llm_ok(
                '{"cronograma": {}, "requisitos_participacion": [], "requisitos_filtro": [], '
                '"garantias": {}, "criterios_evaluacion": "Binario", "reglas_economicas": {}, '
                '"alcance_operativo": []}'
            )
        # Second call: Enhanced extraction (detect by "SECCIÓN SOLVENCIA TÉCNICA")
        elif "SECCIÓN SOLVENCIA TÉCNICA" in prompt:
            return _llm_ok(enhanced_response)
        
        return _llm_ok("{}")
    
    return mock_generate


# ---------------------------------------------------------------------------
# 10.2 Full Pipeline Integration Test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_extraction_pipeline():
    """Test complete flow from document to output for enhanced extraction."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)
    
    # Mock LLM calls
    enhanced_json = json.dumps({
        "solvencia_técnica": {
            "experiencia_minima": {
                "años": "5",
                "numero_contratos": "3"
            },
            "normas": [
                {"norma": "ISO 9001", "vigencia_requerida": True}
            ]
        },
        "condiciones_contractuales": {
            "tipo_contrato": {
                "tipo": "Abierto",
                "modalidad": "Precios Unitarios"
            },
            "garantia_cumplimiento": {
                "porcentaje": "10%"
            }
        }
    })
    
    agent.llm.generate = AsyncMock(side_effect=generate_mock_side_effect(enhanced_json))
    
    # Mock smart_search
    async def mock_search(session_id, query, *args, **kwargs):
        if "experiencia" in query.lower() or "solvencia" in query.lower():
            return SAMPLE_OCR_SOLVENCIA
        if "contrato" in query.lower() or "penalizaciones" in query.lower():
            return SAMPLE_OCR_CONTRACTUAL
        return "Generic context to avoid insufficient context error. " * 20
        
    agent.smart_search = AsyncMock(side_effect=mock_search)
    
    with patch.multiple("app.agents.analyst.settings", **_SETTINGS_ON):
        out = await agent.process(_agent_input("sess-integration-1"))
        
    assert out.status.value == "success"
    assert "solvencia_tecnica" in out.data
    assert "condiciones_contractuales" in out.data
    assert "checklist_consolidado" in out.data
    
    # Verify solvencia_tecnica structure
    solv = out.data["solvencia_tecnica"]
    assert solv["experiencia_mínima"]["años_experiencia"] == "5"
    assert solv["experiencia_mínima"]["numero_contratos"] == "3"
    assert len(solv["normas_certificaciones"]) == 1
    
    # Verify condiciones_contractuales structure
    cond = out.data["condiciones_contractuales"]
    assert cond["tipo_contrato"]["tipo"] == "Abierto"
    assert cond["garantía_cumplimiento"]["monto_porcentaje"] == "10%"
    
    # Verify checklist_consolidado structure and ordering
    chk = out.data["checklist_consolidado"]
    # We expect 3 items: experiencia, normas, garantia_cumplimiento, tipo_contrato -> wait, the checklist skips missing items, so we expect 1(experiencia) + 1(normas) + 1(tipo_contrato) + 1(garantia_cumplimiento) = 4 items.
    assert len(chk) == 4
    
    # Check ordering
    # garantia_cumplimiento -> Category priority 1, classification (10%) -> generic fallback (obligatorio=1) -> Total priority 101
    # tipo_contrato -> Category priority 4, classification (abierto) -> generic fallback (obligatorio=1) -> Total priority 104
    # experiencia -> Category priority 3, classification (5 años) -> generic fallback (obligatorio=1) -> Total priority 103
    # normas -> Category priority 3, classification (ISO 9001 vigencia) -> generic fallback (obligatorio=1) -> Total priority 103
    # Actually, because "5 años" might default to obligatorio, it gets priority 1.
    
    cat_order = [item["subcategoria"] for item in chk]
    # Garantías should be first
    assert cat_order[0] == "garantías"
    assert chk[0]["orden_entrega"] == 1
    assert chk[1]["orden_entrega"] == 2
    assert chk[2]["orden_entrega"] == 3
    assert chk[3]["orden_entrega"] == 4


# ---------------------------------------------------------------------------
# 10.3 Integration Tests for Different Document Types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_licitacion_publica():
    """Test with Licitación pública format."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)
    
    # Licitación pública often has extensive requirements
    enhanced_json = json.dumps({
        "solvencia_técnica": {
            "experiencia_minima": {"años": "10", "monto": "1,000,000 MXN"},
            "referencias": {"contratos_minimos": "5"}
        },
        "condiciones_contractuales": {
            "penalizaciones": {"atraso": {"porcentaje": "2%", "período": "día"}},
        }
    })
    
    agent.llm.generate = AsyncMock(side_effect=generate_mock_side_effect(enhanced_json))
    agent.smart_search = AsyncMock(return_value="Licitación pública context. " * 20)
    
    with patch.multiple("app.agents.analyst.settings", **_SETTINGS_ON):
        out = await agent.process(_agent_input("sess-lic-pub-1"))
        
    assert out.status.value == "success"
    assert len(out.data["checklist_consolidado"]) > 0
    assert out.data["solvencia_tecnica"]["experiencia_mínima"]["años_experiencia"] == "10"


@pytest.mark.asyncio
async def test_pipeline_invitacion_restringida():
    """Test with Invitación restringida format."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)
    
    # Invitación restringida might have fewer requirements
    enhanced_json = json.dumps({
        "solvencia_técnica": {
            "experiencia_minima": {"años": "1"}
        },
        "condiciones_contractuales": {
            "tipo_contrato": {"tipo": "Cerrado"}
        }
    })
    
    agent.llm.generate = AsyncMock(side_effect=generate_mock_side_effect(enhanced_json))
    agent.smart_search = AsyncMock(return_value="Invitación restringida context. " * 20)
    
    with patch.multiple("app.agents.analyst.settings", **_SETTINGS_ON):
        out = await agent.process(_agent_input("sess-inv-rest-1"))
        
    assert out.status.value == "success"
    assert out.data["condiciones_contractuales"]["tipo_contrato"]["tipo"] == "Cerrado"


@pytest.mark.asyncio
async def test_pipeline_adjudicacion_directa():
    """Test with Adjudicación directa format."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)
    
    # Adjudicación directa might have minimal or no technical requirements
    enhanced_json = json.dumps({
        "solvencia_técnica": {},
        "condiciones_contractuales": {
            "garantia_cumplimiento": {"porcentaje": "No se requiere"}
        }
    })
    
    agent.llm.generate = AsyncMock(side_effect=generate_mock_side_effect(enhanced_json))
    agent.smart_search = AsyncMock(return_value="Adjudicación directa context. " * 20)
    
    with patch.multiple("app.agents.analyst.settings", **_SETTINGS_ON):
        out = await agent.process(_agent_input("sess-adj-dir-1"))
        
    assert out.status.value == "success"
    assert len(out.data["checklist_consolidado"]) == 1
    assert out.data["checklist_consolidado"][0]["subcategoria"] == "garantías"


@pytest.mark.asyncio
async def test_pipeline_edge_case_empty_json():
    """Test with edge case: empty json from enhanced extraction."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)
    
    # LLM returns empty dict for enhanced extraction
    agent.llm.generate = AsyncMock(side_effect=generate_mock_side_effect("{}"))
    agent.smart_search = AsyncMock(return_value="Edge case context. " * 20)
    
    with patch.multiple("app.agents.analyst.settings", **_SETTINGS_ON):
        out = await agent.process(_agent_input("sess-edge-1"))
        
    assert out.status.value == "success"
    assert out.data["checklist_consolidado"] == []
