
import pytest
from unittest.mock import AsyncMock, patch
from app.agents.data_gap import DataGapAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.services.resilient_llm import LLMResponse

def _memory_stub(company_data=None):
    mem = AsyncMock()
    mem.get_company = AsyncMock(return_value=company_data)
    mem.save_company = AsyncMock(return_value=True)
    mem.get_session = AsyncMock(return_value={"status": "active"})
    mem.save_session = AsyncMock(return_value=True)
    return mem

def _inp(session_id: str, company_id: str, company_data: dict | None = None) -> AgentInput:
    return AgentInput(
        session_id=session_id,
        company_id=company_id,
        company_data=company_data or {},
    )

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

    with patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):

        result = await agent.process(_inp("sess-1", "co_123"))

    assert result.status == AgentStatus.WAITING_FOR_DATA
    missing_keys = [m["field"] for m in result.data["missing"]]
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

    with patch.object(agent.vector_db, "query_texts", return_value={"documents": ["Contacto: info@test.com"]}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="info@test.com"))):

        result = await agent.process(_inp("sess-1", "co_123"))

    assert "email" in result.data["auto_filled"]
    assert result.status == AgentStatus.SUCCESS
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
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="ventas@mitest.com"))):

        result = await agent.process(_inp("sess-1", "co_123"))

    assert "email" in result.data["auto_filled"]
    assert result.status == AgentStatus.SUCCESS


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
            "representante_legal": "Juan Perez",
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

    result = await agent.process(_inp("sess-1", "co_123"))

    assert result.status == AgentStatus.SUCCESS
    assert len(result.data["missing"]) == 0
    assert "expediente está completo" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_datagap_identifica_slots_desde_compliance_sin_duplicar():
    """Hito 5.1: Verifica que slots inferidos (tax_id) se mapeen a perfil (rfc) y no dupliquen gaps."""

    mock_company = {
        "id": "co_1",
        "master_profile": {
            "razon_social": "Empresa A",
            "rfc": "ABC123456XYZ",
            "representante_legal": "Juan Perez"
        }
    }

    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})

    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    company_data = {
        "compliance_master_list": {
            "administrativo": [{"id": "REQ_1", "nombre": "Presentar RFC", "descripcion": "Cédula de Identificación Fiscal"}]
        }
    }

    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["tax_id"])), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):

        result = await agent.process(_inp("sess-map", "co_1", company_data))

    missing_keys = [m["field"] for m in result.data["missing"]]

    assert "rfc" not in missing_keys
    assert "tax_id" not in missing_keys

    assert "domicilio_fiscal" in missing_keys
