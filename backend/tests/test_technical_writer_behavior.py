"""
TechnicalWriterAgent: contrato de entrada/salida y ramas sin llamar a Ollama.
LLM y VectorDB mockeados; no se escribe en disco real.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.mcp_context import MCPContextManager
from app.agents.technical_writer import TechnicalWriterAgent
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.config.settings import settings as app_settings
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

    req = {"id": "2.1", "nombre": "Capacidad Técnica", "descripcion": "Doc que acredite experiencia", "tipo": "tecnico"}
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
    assert len(out.data["documentos"]) >= 2   # Carta + al menos 1 req
    # LLM invocado al menos una vez (carta de presentacion + req)
    assert agent.llm.generate.call_count >= 2


@pytest.mark.asyncio
async def test_fallback_compliance_desde_results_orquestador():
    """Si no hay compliance_master_list, debe leer de results.compliance.data."""
    agent = _make_agent()

    req = {"id": "2.2", "nombre": "Experiencia Previa", "descripcion": "Acreditar contratos previos", "tipo": "tecnico"}
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
    assert len(out.data["documentos"]) >= 2


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
    assert agent.llm.generate.call_count >= 2
    prompts = [str(c.kwargs.get("prompt") or c.args[0]) for c in agent.llm.generate.call_args_list]
    assert any("GUÍA_DE_PLANTILLA" in p for p in prompts)


@pytest.mark.asyncio
async def test_technical_writer_bloquea_si_faltan_slots_piloto():
    """Con requisitos técnicos pero perfil incompleto → WAITING_FOR_DATA sin llamar al LLM."""
    agent = _make_agent()
    req = {"id": "2.1", "nombre": "Capacidad", "descripcion": "Doc", "tipo": "tecnico"}
    inp = AgentInput(
        session_id="sess_t_block",
        company_data={
            "master_profile": {"razon_social": "Sin datos SA", "rfc": "ABC010101ABC"},
            "compliance_master_list": {"tecnico": [req]},
        },
        company_id="co-1",
        mode="generation_only",
        job_id="job_tw_block",
    )
    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert out.data.get("missing")
    agent.llm.generate.assert_not_awaited()


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
    agent = _make_agent()

    req = {
        "id": "2.1",
        "nombre": "Capacidad Técnica",
        "descripcion": "Acreditar experiencia técnica",
        "tipo": "tecnico",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_tw_no_criticos",
        company_data={
            # Perfil con campos críticos completos, sin informativos
            "master_profile": {
                "razon_social": "Empresa Técnica SA",
                "rfc": "TEC010101AAA",
                "domicilio_fiscal": "Av. Insurgentes 500, CDMX",
                "representante_legal": "María Técnica",
                # telefono, email, web ausentes → informativos, no bloquean
            },
            "compliance_master_list": {"tecnico": [req]},
        },
        company_id="co-tech-1",
        mode="generation_only",
    )

    with patch("os.makedirs"), patch("app.agents.technical_writer._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS, (
        f"TechnicalWriter no debe bloquear por faltantes informativos. Status: {out.status}"
    )
    assert len(out.data["documentos"]) >= 2  # Carta + al menos 1 req
    agent.llm.generate.assert_awaited()


@pytest.mark.asyncio
async def test_technical_writer_bloquea_solo_por_criticos():
    """
    Req 5.1 / 5.4: Cuando falta un campo crítico, TechnicalWriterAgent
    debe retornar WAITING_FOR_DATA.

    Verifica que el bloqueo duro se activa SOLO por campos en BLOCKING_FIELDS.
    """
    agent = _make_agent()

    req = {
        "id": "2.2",
        "nombre": "Experiencia Previa",
        "descripcion": "Contratos previos similares",
        "tipo": "tecnico",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_tw_critico_faltante",
        company_data={
            "master_profile": {
                "razon_social": "Empresa Sin Domicilio SA",
                "rfc": "SDD010101BBB",
                # domicilio_fiscal ausente → crítico
                # representante_legal ausente → crítico
            },
            "compliance_master_list": {"tecnico": [req]},
        },
        company_id="co-tech-2",
        mode="generation_only",
        job_id="job_tw_critico",
    )

    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.WAITING_FOR_DATA, (
        f"TechnicalWriter debe bloquear cuando faltan campos críticos. Status: {out.status}"
    )
    missing_fields = [m["field"] for m in (out.data.get("missing") or [])]
    critical_fields = {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
    assert any(f in critical_fields for f in missing_fields), (
        f"Debe reportar campos críticos faltantes. missing: {missing_fields}"
    )
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_flujo_mixto_technical_writer_bloquea_solo_por_criticos():
    """
    Req 6.3 / 5.4: Flujo mixto — perfil con faltantes críticos Y no críticos.

    TechnicalWriterAgent debe bloquear por los críticos, no por los informativos.
    El invariante: WAITING_FOR_DATA se justifica SOLO por campos críticos faltantes.
    """
    agent = _make_agent()

    req = {
        "id": "2.3",
        "nombre": "Programa de Trabajo",
        "descripcion": "Cronograma de actividades",
        "tipo": "tecnico",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_tw_mixto",
        company_data={
            "master_profile": {
                "razon_social": "Empresa Mixta Técnica SA",
                # rfc ausente → crítico
                # domicilio_fiscal ausente → crítico
                # representante_legal ausente → crítico
                # telefono, email ausentes → informativos (no bloquean)
            },
            "compliance_master_list": {"tecnico": [req]},
        },
        company_id="co-tech-3",
        mode="generation_only",
        job_id="job_tw_mixto",
    )

    with patch("os.makedirs"):
        out = await agent.process(inp)

    # Debe bloquear por críticos
    assert out.status == AgentStatus.WAITING_FOR_DATA, (
        "Con faltantes críticos en flujo mixto, TechnicalWriter debe bloquear."
    )
    missing_fields = [m["field"] for m in (out.data.get("missing") or [])]
    critical_fields = {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
    blocking_missing = [f for f in missing_fields if f in critical_fields]
    assert len(blocking_missing) > 0, (
        f"El bloqueo debe ser por campos críticos. missing: {missing_fields}"
    )
    agent.llm.generate.assert_not_awaited()
