
import pytest
from unittest.mock import AsyncMock, patch
from app.agents.data_gap import DataGapAgent
from app.agents.mcp_context import MCPContextManager

def _memory_stub(company_data=None):
    mem = AsyncMock()
    mem.get_company = AsyncMock(return_value=company_data)
    mem.save_company = AsyncMock(return_value=True)
    mem.get_session = AsyncMock(return_value={"status": "active"})
    mem.save_session = AsyncMock(return_value=True)
    return mem

@pytest.mark.asyncio
async def test_data_gap_identifies_missing_fields():
    # Perfil con campos vacíos o tipo "placeholder"
    mock_company = {
        "id": "co_123",
        "name": "Test Company",
        "master_profile": {
            "razon_social": "Test Company SA",
            "representante_legal": "Juan Perez",
            "cedula_representante": "", # Vacío
            "email": "denuncas@sat.gob.mx", # Basura/Placeholder
            "web": "http", # Mal formado
            "telefono": "123", # Muy corto
            # anos_experiencia y numero_empleados también faltan por omisión
        }
    }
    
    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)
    
    # Mock de RAG y LLM para que no encuentren nada (Canal A falla)
    with patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value={"response": "NO_ENCONTRADO"})):
        
        result = await agent.process("sess-1", {"company_id": "co_123"})
    
    assert result["status"] == "waiting_for_data"
    missing_keys = [m["field"] for m in result["missing"]]
    # FIELD_DEFINITIONS incluye rfc, domicilio_fiscal y representante_legal (Hito 4).
    assert len(missing_keys) == 8
    assert "rfc" in missing_keys
    assert "domicilio_fiscal" in missing_keys
    assert "cedula_representante" in missing_keys
    assert "email" in missing_keys

@pytest.mark.asyncio
async def test_data_gap_auto_fills_from_rag():
    mock_company = {
        "id": "co_123",
        "master_profile": {
            "razon_social": "Test Company SA",
            "representante_legal": "Juan Perez",
            "cedula_representante": "1234567890",
            "telefono": "5512345678",
            "email": "", # Faltante
            "web": "https://test.com",
            "anos_experiencia": "10",
            "numero_empleados": "50"
        }
    }
    
    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)
    
    # Simular que el RAG encuentra el correo
    with patch.object(agent.vector_db, "query_texts", return_value={"documents": ["Contacto: info@test.com"]}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value={"response": "info@test.com"})):
        
        result = await agent.process("sess-1", {"company_id": "co_123"})
    
    assert "email" in result["auto_filled"]
    assert result["status"] == "complete"
    ctx.memory.save_company.assert_awaited_once()

@pytest.mark.asyncio
async def test_data_gap_auto_fills_from_session_expediente_pdf():
    """RAG en sesión solo sobre archivos que no parecen bases/convocatoria."""
    mock_company = {
        "id": "co_123",
        "master_profile": {
            "razon_social": "Test Company SA",
            "representante_legal": "Juan Perez",
            "cedula_representante": "1234567890",
            "telefono": "5512345678",
            "email": "",
            "web": "https://test.com",
            "anos_experiencia": "10",
            "numero_empleados": "50",
        },
    }

    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)

    def fake_query_texts(coll: str, query: str, n_results: int = 5):
        return {"documents": []}

    def fake_filtered(sid: str, query: str, source_filter: str, n_results: int = 20):
        if source_filter == "CIF_EMPRESA.pdf":
            return {"documents": ["Correo de contacto: ventas@mitest.com"]}
        return {"documents": []}

    with patch.object(agent.vector_db, "query_texts", side_effect=fake_query_texts), \
         patch.object(agent.vector_db, "query_texts_filtered", side_effect=fake_filtered), \
         patch.object(agent.vector_db, "get_sources", return_value=["CONVOCATORIA_2024.pdf", "CIF_EMPRESA.pdf"]), \
         patch.object(agent.llm, "generate", AsyncMock(return_value={"response": "ventas@mitest.com"})):

        result = await agent.process("sess-1", {"company_id": "co_123"})

    assert "email" in result["auto_filled"]
    assert result["status"] == "complete"


def test_filename_looks_like_bases():
    assert DataGapAgent._filename_looks_like_bases("Bases_Licitacion.pdf") is True
    assert DataGapAgent._filename_looks_like_bases("mi_cif_sat.pdf") is False


@pytest.mark.asyncio
async def test_data_gap_skips_valid_data():
    mock_company = {
        "id": "co_123",
        "master_profile": {
            "razon_social": "Test Company SA",
            "rfc": "TES123456ABC",
            "domicilio_fiscal": "Insurgentes Sur 1000, CDMX",
            "representante_legal": "Juan Perez", # Importante para formateo de preguntas si fallara
            "cedula_representante": "INE-1234567890",
            "email": "real@company.com",
            "web": "https://company.com",
            "telefono": "55 1234 5678",
            "anos_experiencia": "10",
            "numero_empleados": "50"
        }
    }
    
    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)
    
    result = await agent.process("sess-1", {"company_id": "co_123"})
    
    assert result["status"] == "complete"
    assert len(result["missing"]) == 0
    assert "expediente está completo" in result["chatbot_message"]


@pytest.mark.asyncio
async def test_datagap_identifica_slots_desde_compliance_sin_duplicar():
    """Hito 5.1: Verifica que slots inferidos (tax_id) se mapeen a perfil (rfc) y no dupliquen gaps."""
    
    # 1. Perfil con RFC ya lleno, pero otros campos vacíos (ej. domicilio)
    mock_company = {
        "id": "co_1",
        "master_profile": {
            "razon_social": "Empresa A",
            "rfc": "ABC123456XYZ",
            "representante_legal": "Juan Perez"
        }
    }
    
    mem = _memory_stub(mock_company)
    # Simular que el cache está vacío
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    # 2. Simular que compliance requiere RFC (SlotInference -> tax_id)
    input_data = {
        "company_id": "co_1",
        "compliance_master_list": {
            "administrativo": [{"id": "REQ_1", "nombre": "Presentar RFC", "descripcion": "Cédula de Identificación Fiscal"}]
        }
    }

    # Mockear el inferidor de slots para que devuelva 'tax_id'
    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["tax_id"])), \
         patch.object(agent.llm, "generate", AsyncMock(return_value={"response": "NO_ENCONTRADO"})):
        
        # Ejecutar
        result = await agent.process("sess-map", input_data)

    # 3. Validaciones
    missing_keys = [m["field"] for m in result["missing"]]
    
    # 'tax_id' se mapeó a 'rfc', y 'rfc' ya tiene valor -> NO debe estar en missing
    assert "rfc" not in missing_keys
    assert "tax_id" not in missing_keys
    
    # Otros campos obligatorios (como domicilio_fiscal) sí deben estar en missing
    assert "domicilio_fiscal" in missing_keys
