
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
    # Sin compliance: solo se evalúan bloqueantes; cédula/email/teléfono no entran al conjunto activo.
    assert "rfc" in missing_keys
    assert "domicilio_fiscal" in missing_keys
    assert "cedula_representante" not in missing_keys
    assert "email" not in missing_keys
    assert set(result.data["missing_blocking"]) == {"rfc", "domicilio_fiscal"}

@pytest.mark.asyncio
async def test_data_gap_auto_fills_from_rag():
    mock_company = {
        "id": "co_123",
        "master_profile": {
            "razon_social": "Test Company SA",
            "representante_legal": "Juan Perez",
            "rfc": "TES123456ABC",
            "domicilio_fiscal": "Calle 1, CDMX",
            "cedula_representante": "1234567890",
            "telefono": "5512345678",
            "email": "",  # Faltante pero solo se evalúa si compliance infiere email
            "web": "https://test.com",
            "anos_experiencia": "10",
            "numero_empleados": "50",
        }
    }

    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    company_data = {
        "compliance_master_list": {
            "administrativo": [
                {"id": "REQ_MAIL", "nombre": "Correo", "descripcion": "correo electrónico de contacto"}
            ]
        }
    }

    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["email"])), \
         patch.object(agent.vector_db, "query_texts", return_value={"documents": ["Contacto: info@test.com"]}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="info@test.com"))):

        result = await agent.process(_inp("sess-1", "co_123", company_data))

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
            "rfc": "TES123456ABC",
            "domicilio_fiscal": "Calle 1, CDMX",
            "cedula_representante": "1234567890",
            "telefono": "5512345678",
            "email": "",
            "web": "https://test.com",
            "anos_experiencia": "10",
            "numero_empleados": "50",
        },
    }

    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    company_data = {
        "compliance_master_list": {
            "administrativo": [
                {"id": "REQ_MAIL2", "nombre": "Correo", "descripcion": "correo electrónico"}
            ]
        }
    }

    def fake_query_texts(coll: str, query: str, n_results: int = 5):
        return {"documents": []}

    def fake_filtered(sid: str, query: str, source_filter: str, n_results: int = 20):
        if source_filter == "CIF_EMPRESA.pdf":
            return {"documents": ["Correo de contacto: ventas@mitest.com"]}
        return {"documents": []}

    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["email"])), \
         patch.object(agent.vector_db, "query_texts", side_effect=fake_query_texts), \
         patch.object(agent.vector_db, "query_texts_filtered", side_effect=fake_filtered), \
         patch.object(agent.vector_db, "get_sources", return_value=["CONVOCATORIA_2024.pdf", "CIF_EMPRESA.pdf"]), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="ventas@mitest.com"))):

        result = await agent.process(_inp("sess-1", "co_123", company_data))

    assert "email" in result.data["auto_filled"]
    assert result.status == AgentStatus.SUCCESS


def test_filename_looks_like_bases():
    assert DataGapAgent._filename_looks_like_bases("Bases_Licitacion.pdf") is True
    assert DataGapAgent._filename_looks_like_bases("mi_cif_sat.pdf") is False


def test_truth_source_filter_excluye_plantillas_de_oferta():
    assert DataGapAgent._source_looks_like_truth_source("CIF_EMPRESA.pdf") is True
    assert DataGapAgent._source_looks_like_truth_source("Anexo III P 1 Zona A.xlsx") is False
    assert DataGapAgent._source_looks_like_truth_source("Anexo F Constancia de Visitas.xlsx") is False
    assert DataGapAgent._source_looks_like_truth_source("Aclaraciones.pdf") is False
    assert DataGapAgent._source_looks_like_truth_source("Bases_Licitacion.pdf") is False


def test_representante_legal_descarta_valores_genericos():
    agent = DataGapAgent(MCPContextManager(_memory_stub({})))
    assert agent._is_data_valid("representante_legal", "PERSONAL") is False
    assert agent._is_data_valid("representante_legal", "Representante Legal") is False
    assert agent._is_data_valid("representante_legal", "Juan Pérez") is True


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
async def test_data_gap_filtra_fuentes_de_sesion_y_no_usa_anexos_como_verdad_corporativa():
    mock_company = {
        "id": "co_truth",
        "master_profile": {
            "razon_social": "Empresa Truth SA",
            "representante_legal": "Juan Perez",
            "rfc": "TES123456ABC",
            "domicilio_fiscal": "Calle 1, CDMX",
            "email": "",
        },
    }
    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    mem.get_documents = AsyncMock(
        return_value=[
            {"content": {"filename": "16. Anexo III P 1 Zona A.xlsx"}, "metadata": {}},
            {"content": {"filename": "CIF_EMPRESA.pdf"}, "metadata": {}},
            {"content": {"filename": "Bases_Licitacion.pdf"}, "metadata": {}},
        ]
    )
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    company_data = {
        "compliance_master_list": {
            "administrativo": [
                {"id": "REQ_MAIL3", "nombre": "Correo", "descripcion": "correo electrónico"}
            ]
        }
    }
    filtered_calls = []

    def fake_query_texts(coll: str, query: str, n_results: int = 5):
        if coll == "company_co_truth":
            return {"documents": []}
        return {"documents": [], "metadatas": []}

    def fake_filtered(sid: str, query: str, source_filter: str, n_results: int = 20):
        filtered_calls.append(source_filter)
        if source_filter == "CIF_EMPRESA.pdf":
            return {"documents": ["Correo de contacto: truth@empresa.com"]}
        return {"documents": []}

    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["email"])), \
         patch.object(agent.vector_db, "query_texts", side_effect=fake_query_texts), \
         patch.object(agent.vector_db, "query_texts_filtered", side_effect=fake_filtered), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="truth@empresa.com"))):
        result = await agent.process(_inp("sess-truth", "co_truth", company_data))

    assert "email" in result.data["auto_filled"]
    assert "CIF_EMPRESA.pdf" in filtered_calls
    assert "16. Anexo III P 1 Zona A.xlsx" not in filtered_calls


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


@pytest.mark.asyncio
async def test_data_gap_informational_fields_enqueued_without_blocking():
    """Sin requisitos que infieran slots informativos, no se encolan cédula/web/teléfono/etc."""
    mock_company = {
        "id": "co_inf",
        "master_profile": {
            "razon_social": "SA de CV",
            "rfc": "ABC123456XYZ",
            "domicilio_fiscal": "Calle 1, CDMX",
            "representante_legal": "Ana López",
            "cedula_representante": "",
            "web": "",
            "telefono": "",
            "email": "",
        },
    }
    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)
    with patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):
        result = await agent.process(_inp("sess-inf", "co_inf"))
    assert result.status == AgentStatus.SUCCESS
    missing_keys = [m["field"] for m in result.data["missing"]]
    assert missing_keys == []
    assert result.data["missing_blocking"] == []


@pytest.mark.asyncio
async def test_data_gap_blocking_fields_enqueued():
    """RFC, razón social, domicilio y representante sí encolan HITL si faltan tras RAG."""
    mock_company = {
        "id": "co_blk",
        "master_profile": {},
    }
    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)
    with patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):
        result = await agent.process(_inp("sess-blk", "co_blk"))
    missing_keys = [m["field"] for m in result.data["missing"]]
    assert set(result.data["missing_blocking"]) == {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
    assert set(result.data["missing_blocking"]).issubset(set(missing_keys))


@pytest.mark.asyncio
async def test_datagap_no_encola_numero_empleados_sin_inferencia_de_plantilla():
    """Bases que solo exigen RFC (tax_id) no deben abrir brecha de plantilla laboral."""
    mock_company = {
        "id": "co_ne",
        "master_profile": {
            "razon_social": "X SA de CV",
            "rfc": "ABC123456XYZ",
            "domicilio_fiscal": "Calle 2, CDMX",
            "representante_legal": "Pepe Pérez",
        },
    }
    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)
    company_data = {
        "compliance_master_list": {
            "administrativo": [
                {"id": "R1", "nombre": "CIF", "descripcion": "RFC vigente del oferente"},
            ]
        },
    }
    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["tax_id"])), \
         patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):
        result = await agent.process(_inp("sess-ne", "co_ne", company_data))
    missing_keys = [m["field"] for m in result.data["missing"]]
    assert "numero_empleados" not in missing_keys
    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_data_gap_marks_is_blocking_flag():
    mock_company = {
        "id": "co_mix",
        "master_profile": {
            "razon_social": "Empresa Demo SA de CV",
            "rfc": "",
            "domicilio_fiscal": "Av Siempre Viva 123",
            "representante_legal": "Ana Ruiz",
            "email": "",
        },
    }
    ctx = MCPContextManager(_memory_stub(mock_company))
    agent = DataGapAgent(ctx)
    with patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):
        result = await agent.process(_inp("sess-mix", "co_mix"))

    by_field = {m["field"]: m for m in result.data["missing"]}
    assert by_field["rfc"]["is_blocking"] is True
    assert "email" not in by_field


@pytest.mark.asyncio
async def test_data_gap_invariants_no_overlap_auto_filled_and_missing():
    """Un campo auto-extraído no debe aparecer en missing."""
    # Perfil con email vacío que se auto-extrae desde RAG
    mock_company = {
        "id": "co_inv",
        "master_profile": {
            "razon_social": "Empresa Inv SA",
            "rfc": "INV123456ABC",
            "domicilio_fiscal": "Calle Inv 1",
            "representante_legal": "Inv Rep",
            "email": "",  # Faltante, pero se auto-extraerá
        },
    }
    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)
    company_data = {
        "compliance_master_list": {
            "administrativo": [{"id": "R_EMAIL", "nombre": "Correo", "descripcion": "email de contacto"}]
        }
    }
    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["email"])), \
         patch.object(agent.vector_db, "query_texts", return_value={"documents": ["Contacto: inv@empresa.com"]}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="inv@empresa.com"))):
        result = await agent.process(_inp("sess-inv", "co_inv", company_data))

    # Invariante: email no puede estar en ambos
    auto_filled_set = set(result.data["auto_filled"])
    missing_keys = {m["field"] for m in result.data["missing"]}
    assert auto_filled_set.isdisjoint(missing_keys), f"Overlap: {auto_filled_set & missing_keys}"

    # Invariante: missing_blocking es subconjunto de missing
    assert set(result.data["missing_blocking"]).issubset(missing_keys)


@pytest.mark.asyncio
async def test_data_gap_informational_field_enqueued_with_is_blocking_false():
    """
    Caso requerido: faltante informativo se encola con is_blocking=False.

    Cuando un campo informativo (email) se infiere desde compliance y no tiene
    valor válido ni puede auto-extraerse desde RAG, debe aparecer en `missing`
    con is_blocking=False y NO aparecer en missing_blocking.
    """
    mock_company = {
        "id": "co_info_blk",
        "master_profile": {
            "razon_social": "Empresa Info SA",
            "rfc": "INF123456ABC",
            "domicilio_fiscal": "Calle Info 1, CDMX",
            "representante_legal": "Info Rep",
            "email": "",  # Faltante informativo
        },
    }
    mem = _memory_stub(mock_company)
    mem.get_session = AsyncMock(return_value={"compliance_slot_cache": {}})
    ctx = MCPContextManager(mem)
    agent = DataGapAgent(ctx)

    # Compliance que infiere el slot "email" (campo informativo)
    company_data = {
        "compliance_master_list": {
            "administrativo": [
                {"id": "R_EMAIL2", "nombre": "Correo electrónico", "descripcion": "email de contacto del oferente"}
            ]
        }
    }

    with patch.object(agent.slot_inferer, "infer_all", AsyncMock(return_value=["email"])), \
         patch.object(agent.vector_db, "query_texts", return_value={"documents": []}), \
         patch.object(agent.llm, "generate", AsyncMock(return_value=LLMResponse(success=True, response="NO_ENCONTRADO"))):
        result = await agent.process(_inp("sess-info-blk", "co_info_blk", company_data))

    by_field = {m["field"]: m for m in result.data["missing"]}

    # El campo informativo debe estar en missing con is_blocking=False
    assert "email" in by_field, "El campo informativo 'email' debe aparecer en missing"
    assert by_field["email"]["is_blocking"] is False, "El campo informativo debe tener is_blocking=False"

    # No debe aparecer en missing_blocking
    assert "email" not in result.data["missing_blocking"], "El campo informativo no debe estar en missing_blocking"

    # El status no debe ser WAITING_FOR_DATA (solo bloqueantes lo activan)
    from app.contracts.agent_contracts import AgentStatus
    assert result.status == AgentStatus.SUCCESS, "Faltantes informativos no deben bloquear generación"
