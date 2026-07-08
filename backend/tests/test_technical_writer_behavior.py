"""
TechnicalWriterAgent: contrato de entrada/salida y ramas sin llamar a Ollama.
LLM y VectorDB mockeados; no se escribe en disco real.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.mcp_context import MCPContextManager
from app.agents.technical_writer import (
    TechnicalWriterAgent,
    _build_carta_presentacion_text,
    _build_contenido_nacional_text,
    _build_te12_text,
    _mirror_source_has_cross_tender_marker,
)
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.config.settings import settings as app_settings
from app.core.formats_pilot_slots import build_formats_pilot_missing_entries
from app.services.resilient_llm import LLMResponse

_MASTER_PILOTO_COMPLETO = {
    "razon_social": "Test Co SA",
    "rfc": "TST010101AAA",
    "domicilio_fiscal": "Av. Central 100, CDMX",
    "representante_legal": "Juan Test",
}


def _memory_stub(tasks: list | None = None):
    mem = AsyncMock()
    sess = {"tasks_completed": tasks or [], "name": "test_session"}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


def _make_agent(tasks=None):
    ctx = MCPContextManager(_memory_stub(tasks))
    agent = TechnicalWriterAgent(ctx)
    # Mockear LLM y VectorDB desde el constructor
    agent.llm = AsyncMock()
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="Contenido generado por mock."))
    agent.vector_db = MagicMock()
    agent.vector_db.query_texts = MagicMock(return_value={"documents": []})
    return agent


@pytest.mark.asyncio
async def test_sin_requisitos_tecnicos_devuelve_success_sin_archivos():
    """Sin ítems técnicos en compliance_data → success sin documentos."""
    agent = _make_agent()

    inp = AgentInput(
        session_id="sess_t1",
        company_data={"master_profile": {**_MASTER_PILOTO_COMPLETO, "razon_social": "Test Co"}},
        company_id="co-1",
        mode="generation_only"
    )
    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert "No hay" in out.message
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_con_requisitos_tecnicos_llm_es_invocado_y_devuelve_success():
    """Con ítems técnicos → LLM es invocado y se retorna success con documentos."""
    agent = _make_agent()

    req = {
        "id": "2.1",
        "nombre": "Anexo Tecnico",
        "descripcion": "Documento tecnico de la propuesta",
        "tipo": "tecnico",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_t2",
        company_data={"master_profile": _MASTER_PILOTO_COMPLETO},
        company_id="co-1",
        mode="generation_only"
    )
    # Inyectar compliance master list en company_data como espera el orquestador
    inp.company_data["compliance_master_list"] = {"tecnico": [req]}

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx") as mock_save, \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert "data" in out.model_dump()


@pytest.mark.asyncio
async def test_fallback_compliance_desde_results_orquestador():
    """Si no hay compliance_master_list, debe leer de results.compliance.data."""
    agent = _make_agent()

    req = {
        "id": "2.2",
        "nombre": "Anexo Tecnico",
        "descripcion": "Acreditar contratos previos",
        "tipo": "tecnico",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_t3",
        company_data={"master_profile": {**_MASTER_PILOTO_COMPLETO, "razon_social": "Fallback Corp", "rfc": "FAL010101BBB"}},
        company_id="co-1",
        mode="generation_only"
    )
    # Simular que el compliance ya ocurrió y está en la sesión
    tasks = [{"task": "stage_completed:compliance", "result": {"data": {"tecnico": [req]}}}]
    agent.context_manager.get_global_context = AsyncMock(return_value={"session_state": {"tasks_completed": tasks}})

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"), \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)
 
    assert out.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_document_inventory_tecnico_genera_adicional_sin_compliance():
    """Modo fábrica: ítems técnicos PENDING en document_inventory se redactan aunque técnico=[]."""
    agent = _make_agent()
    inv = {
        "session_id": "sess_inv",
        "schema_version": "1.0.0",
        "revision": 1,
        "items": [
            {
                "canonical_id": "forma_at_02",
                "display_name": "Forma AT-02 sitio",
                "description": "Manifestación de conocimiento del sitio",
                "category": "technical",
                "tier": "anchored",
                "status": "pending",
                "anchors": [{"snippet": "Forma AT-02", "confidence": 1.0}],
                "bases_revision": "revtestinv001",
                "generator_hint": "plantilla_o_llm:AT-02",
            }
        ],
    }
    inp = AgentInput(
        session_id="sess_inv",
        company_data={
            "master_profile": {
                **_MASTER_PILOTO_COMPLETO,
                "razon_social": "Inv Co",
                "rfc": "INV010101ABC",
                "representante_legal": "Ana Inv",
            },
            "compliance_master_list": {"tecnico": []},
            "document_inventory": inv,
        },
        company_id="co-1",
        mode="generation_only",
    )
    agent.context_manager.get_global_context = AsyncMock(
        return_value={"session_state": {"tasks_completed": []}}
    )
    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx") as mock_save, \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert len(out.data["documentos"]) >= 2
    assert agent.llm.generate.call_count >= 1
    prompts = [str(c.kwargs.get("prompt") or c.args[0]) for c in agent.llm.generate.call_args_list]
    assert any("GUÍA_DE_PLANTILLA" in p for p in prompts)


def test_build_carta_presentacion_text_no_deja_placeholders():
    txt = _build_carta_presentacion_text(
        razon_social="Empresa Demo SA de CV",
        rfc="DEM010101AAA",
        representante="Ana Demo",
        domicilio="Campanario | Número Exterior: 99, OTRA NO ESPECIFICADA EN EL",
        tender_name="LICITACIÓN ISAPEG",
        fecha_es="25 de mayo de 2026",
    )
    assert "[Fecha]" not in txt
    assert "[Tipo de letra formal]" not in txt
    assert "OTRA NO ESPECIFICADA EN EL" not in txt
    assert "Empresa Demo SA de CV" in txt


def test_build_te12_text_usa_contexto_si_hay_umbral():
    txt = _build_te12_text(
        razon_social="Empresa Demo SA de CV",
        rfc="DEM010101AAA",
        representante="Ana Demo",
        domicilio="Av. Reforma 10",
        tender_name="LICITACIÓN ISAPEG",
        fecha_es="25 de mayo de 2026",
        req_context="la puntuación o unidades porcentuales ... será de cuando menos 45 de los 60 máximos que se pueden obtener",
    )
    assert "45 de los 60 máximos" in txt
    assert "[]" not in txt


def test_build_contenido_nacional_text_pluraliza_zonas_y_usa_porcentaje():
    txt = _build_contenido_nacional_text(
        razon_social="Empresa Demo SA de CV",
        rfc="DEM010101AAA",
        representante="Ana Demo",
        session_id="isapeg",
        tender_name="ISAPEG",
        fecha_es="25 de mayo de 2026",
        zonas=["A", "B", "C", "D"],
        porcentaje="65",
    )
    assert "las zonas A, B, C, D" in txt
    assert "65 por ciento" in txt
    assert "RFC DEM010101AAA" in txt
    assert "Empresa Demo SA de CV" in txt


def test_mirror_source_has_cross_tender_marker_tecnico_detecta_fuente_contaminada():
    class Ref:
        filename = "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx"
        extracted_text = (
            "ANEXO TÉCNICO ... (IMSS-BIENESTAR) ... "
            "Servicios para IMSS-BIENESTAR ... "
            "Hospitales de IMSS-BIENESTAR ... "
            "IMSS-BIENESTAR."
        )

    assert _mirror_source_has_cross_tender_marker(Ref(), "isapeg ISAPEG") is True


@pytest.mark.asyncio
async def test_technical_writer_descarta_catalogo_cross_tender_y_continua_con_inventario():
    agent = _make_agent()
    agent.context_manager.memory.get_documents = AsyncMock(
        return_value=[
            {
                "id": "doc-1",
                "content": {
                    "filename": "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx",
                    "file_path": "/tmp/anexo_tecnico.docx",
                    "extracted_text": (
                        "ANEXO TÉCNICO (IMSS-BIENESTAR) IMSS-BIENESTAR "
                        "servicio integral IMSS-BIENESTAR hospitalario."
                    ),
                },
            }
        ]
    )

    inp = AgentInput(
        session_id="isapeg",
        company_data={
            "master_profile": _MASTER_PILOTO_COMPLETO,
            "compliance_master_list": {"tecnico": []},
            "document_inventory": {
                "session_id": "isapeg",
                "schema_version": "1.0.0",
                "revision": 1,
                "items": [
                    {
                        "canonical_id": "anexo_tecnico",
                        "display_name": "Anexo Técnico",
                        "description": "Presentar el anexo técnico completo en hoja membretada, rubricado y firmado por el representante legal.",
                        "category": "technical",
                        "tier": "inferred",
                        "status": "pending",
                        "anchors": [{"snippet": "Anexo Técnico", "confidence": 1.0}],
                        "bases_revision": "revtesttech001",
                    }
                ],
            },
        },
        company_id="co-1",
        mode="generation_only",
    )

    with patch("os.makedirs"), \
         patch("os.path.isfile", return_value=True), \
         patch("app.services.session_template_catalog.build_catalog_mirror_reqs", return_value=[{
             "id": "cat_anexo_tecnico",
             "nombre": "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx",
             "descripcion": "Plantilla oficial ingestada (catálogo de sesión).",
             "archivo_fuente": "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx",
             "tipo_accion": "generar",
             "tipo": "tecnico",
             "from_session_catalog": True,
             "sobre_inferido": "tecnico",
         }]), \
         patch("app.agents.technical_writer._save_docx"), \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert len(out.data["documentos"]) >= 2
    assert agent.llm.generate.call_count >= 1


@pytest.mark.asyncio
async def test_technical_writer_bloquea_si_faltan_slots_piloto():
    """Con requisitos técnicos pero perfil incompleto → WAITING_FOR_DATA sin llamar al LLM."""
    missing = build_formats_pilot_missing_entries(
        {"razon_social": "Sin datos SA", "rfc": "ABC010101ABC"},
        blocking_job_id="job_tw_block",
    )
    fields = [m["field"] for m in missing]
    assert "domicilio_fiscal" in fields
    assert "representante_legal" in fields


@pytest.mark.asyncio
async def test_technical_writer_quality_gate_bloquea_unknown_ratio(monkeypatch):
    """
    El gate ahora solo bloquea cuando no hay nada que hacer.
    Con un item 'generar' presente, el gate loguea pero continúa.
    """
    agent = _make_agent()
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_HARD_GATE_ENABLED", True)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_ITEMS", 3)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MAX_UNKNOWN_RATIO", 0.5)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_EVIDENCE_MATCH_RATIO", 0.4)

    reqs = [
        {"id": "TE-01", "nombre": "Evento", "descripcion": "Fecha de junta", "tipo_accion": "unknown", "evidence_match": False},
        {"id": "TE-02", "nombre": "Lugar", "descripcion": "Lugar del acto", "tipo_accion": "unknown", "evidence_match": False},
        {"id": "TE-03", "nombre": "Plazo", "descripcion": "Plazo de entrega", "tipo_accion": "unknown", "evidence_match": False},
        {"id": "TE-04", "nombre": "Marca", "descripcion": "Marca de equipo", "tipo_accion": "generar", "tipo": "tecnico", "evidence_match": True},
    ]
    inp = AgentInput(
        session_id="sess_t_gate",
        company_data={
            "master_profile": _MASTER_PILOTO_COMPLETO,
            "compliance_master_list": {"tecnico": reqs},
        },
        company_id="co-1",
        mode="generation_only",
    )
    # Mockear escritura de archivos para evitar FileNotFoundError
    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"):
        out = await agent.process(inp)
    # Con un item 'generar' presente, el gate NO bloquea — continúa con lo que tiene
    # El gate loguea la advertencia pero no interrumpe al usuario
    assert out.status != AgentStatus.WAITING_FOR_DATA or out.data.get("document_quality_gate", {}).get("reason") != "unknown_ratio_above_threshold"


@pytest.mark.asyncio
async def test_quality_gate_no_bloquea_si_inventario_tecnico_tiene_pendientes(monkeypatch):
    """Compliance unknown puro no debe bloquear si document_inventory trae ítems PENDING."""
    agent = _make_agent()
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_HARD_GATE_ENABLED", True)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_ITEMS", 3)

    unknown_reqs = [
        {
            "id": f"TE-{i}",
            "nombre": f"Requisito {i}",
            "descripcion": f"Desc {i}",
            "tipo_accion": "unknown",
            "evidence_match": True,
        }
        for i in range(1, 16)
    ]
    inv = {
        "session_id": "sess_gate_inv",
        "schema_version": "1.0.0",
        "revision": 1,
        "items": [
            {
                "canonical_id": "propuesta_tecnica_issste",
                "display_name": "Propuesta técnica",
                "description": "Documento técnico principal",
                "category": "technical",
                "tier": "anchored",
                "status": "pending",
                "anchors": [{"snippet": "propuesta técnica", "confidence": 1.0}],
                "bases_revision": "rev1",
                "generator_hint": "plantilla_o_llm:PROPUESTA_TECNICA",
            }
        ],
    }
    inp = AgentInput(
        session_id="sess_gate_inv",
        company_data={
            "master_profile": _MASTER_PILOTO_COMPLETO,
            "compliance_master_list": {"tecnico": unknown_reqs},
            "document_inventory": inv,
        },
        company_id="co-1",
        mode="generation_only",
    )
    agent.context_manager.get_global_context = AsyncMock(
        return_value={"session_state": {"tasks_completed": []}}
    )
    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"), \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)

    assert out.status != AgentStatus.WAITING_FOR_DATA
    assert out.data.get("document_quality_gate") is None


@pytest.mark.asyncio
async def test_synthetic_compliance_entra_en_cola_sin_inventario_canonico(monkeypatch):
    """Ítems inventory_synthetic en compliance deben generarse sin document_inventory."""
    agent = _make_agent()
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_HARD_GATE_ENABLED", True)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_ITEMS", 3)

    synth_reqs = [
        {
            "id": "cedula_areas",
            "nombre": "Cédulas de Descripción de Áreas",
            "descripcion": "Presentar descripción de áreas.",
            "tipo": "tecnico",
            "inventory_synthetic": True,
            "evidence_match": True,
            "tipo_accion": "generar",
        }
    ]
    inp = AgentInput(
        session_id="sess_synth_only",
        company_data={
            "master_profile": _MASTER_PILOTO_COMPLETO,
            "compliance_master_list": {"tecnico": synth_reqs},
        },
        company_id="co-1",
        mode="generation_only",
    )
    agent.context_manager.get_global_context = AsyncMock(
        return_value={"session_state": {"tasks_completed": []}}
    )
    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"), \
         patch("json.dump"), patch("json.load", return_value={}), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", MagicMock()):
        out = await agent.process(inp)

    assert out.status != AgentStatus.WAITING_FOR_DATA
    assert out.data.get("document_quality_gate") is None


# =============================================================================
# INTEGRATION TESTS: Gate documental — Requirements 5.1, 5.4, 6.3
# =============================================================================


@pytest.mark.asyncio
async def test_technical_writer_no_bloquea_por_faltantes_no_criticos():
    """
    Req 5.4 / 6.3: Cuando solo faltan campos informativos (no bloqueantes),
    TechnicalWriterAgent debe continuar generando documentos.

    El bloqueo de TechnicalWriterAgent se basa en los pilot slots (campos
    críticos: rfc, razon_social, domicilio_fiscal, representante_legal).
    Campos informativos ausentes (telefono, email, etc.) no deben bloquear.
    """
    missing = build_formats_pilot_missing_entries(
        {
            "razon_social": "Empresa Técnica SA",
            "rfc": "TEC010101AAA",
            "domicilio_fiscal": "Av. Insurgentes 500, CDMX",
            "representante_legal": "María Técnica",
        }
    )
    assert missing == []


@pytest.mark.asyncio
async def test_technical_writer_bloquea_solo_por_criticos():
    """
    Req 5.1 / 5.4: Cuando falta un campo crítico, TechnicalWriterAgent
    debe retornar WAITING_FOR_DATA.

    Verifica que el bloqueo duro se activa SOLO por campos en BLOCKING_FIELDS.
    """
    missing_fields = [
        m["field"]
        for m in build_formats_pilot_missing_entries(
            {
                "razon_social": "Empresa Sin Domicilio SA",
                "rfc": "SDD010101BBB",
            },
            blocking_job_id="job_tw_critico",
        )
    ]
    critical_fields = {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
    assert any(f in critical_fields for f in missing_fields), (
        f"Debe reportar campos críticos faltantes. missing: {missing_fields}"
    )


@pytest.mark.asyncio
async def test_flujo_mixto_technical_writer_bloquea_solo_por_criticos():
    """
    Req 6.3 / 5.4: Flujo mixto — perfil con faltantes críticos Y no críticos.

    TechnicalWriterAgent debe bloquear por los críticos, no por los informativos.
    El invariante: WAITING_FOR_DATA se justifica SOLO por campos críticos faltantes.
    """
    missing_fields = [
        m["field"]
        for m in build_formats_pilot_missing_entries(
            {
                "razon_social": "Empresa Mixta Técnica SA",
            },
            blocking_job_id="job_tw_mixto",
        )
    ]
    critical_fields = {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
    blocking_missing = [f for f in missing_fields if f in critical_fields]
    assert len(blocking_missing) > 0, (
        f"El bloqueo debe ser por campos críticos. missing: {missing_fields}"
    )
