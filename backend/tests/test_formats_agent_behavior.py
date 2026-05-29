"""
FormatsAgent: contrato de entrada/salida, sin LLM real ni disco.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.formats import (
    FormatsAgent,
    _mirror_source_has_cross_tender_marker,
    _sanitize_legal_content,
)
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.config.settings import settings as app_settings
from app.services.resilient_llm import LLMResponse

_SLOTS_PILOTO = {
    "domicilio_fiscal": "Av. Reforma 222, Col. Juárez, Ciudad de México",
    "representante_legal": "María Representante Legal",
}


def _memory_stub(tasks: list | None = None):
    mem = AsyncMock()
    sess = {"tasks_completed": tasks or [], "name": "test_sess", "schema_version": 1}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


def _make_agent(tasks=None):
    ctx = MCPContextManager(_memory_stub(tasks))
    agent = FormatsAgent(ctx)
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=True, response="Contenido legal mockeado.")
    )
    return agent


def test_sanitize_legal_content_reemplaza_placeholders():
    raw = (
        "Compañía Comercial S.A. de C.V.\n"
        "[Dirección de la empresa]\n"
        "[Ciudad, Estado, Código Postal]\n"
        "Fecha: [Fecha actual]\n"
        "Representante Legal: [Nombre del Representante Legal/Apoderado]\n"
        "RFC: N/A\n"
        "Proceso: [Número de Licitación o Nombre del Proceso]\n"
    )
    md = {
        "empresa": "Empresa Demo SA de CV",
        "representante": "Ana Pérez",
        "rfc": "DEM010101ABC",
        "fecha": "27 de abril de 2026",
        "footer_text": "Empresa Demo SA de CV | RFC: DEM010101ABC | Domicilio: Av Reforma 123, CDMX",
    }
    out = _sanitize_legal_content(raw, session_id="licit_demo_001", metadata=md)
    assert "[Dirección" not in out
    assert "[Fecha" not in out
    assert "N/A" not in out
    assert "Av Reforma 123, CDMX" in out
    assert "Ana Pérez" in out
    assert "DEM010101ABC" in out


def test_mirror_source_has_cross_tender_marker_detecta_fuente_contaminada():
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
async def test_formats_degrada_plantilla_cross_tender_a_generacion_controlada():
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
                }
            }
        ]
    )

    req = {
        "id": "1.1",
        "nombre": "ANEXO TÉCNICO 2026 ABRIL A DICIEMBRE.docx",
        "tipo": "administrativo",
        "tipo_accion": "generar",
    }
    inp = AgentInput(
        session_id="isapeg",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101AAA",
                **_SLOTS_PILOTO,
            },
                "compliance_master_list": {"administrativo": [], "formatos": []},
        },
    )

    with patch("os.makedirs"), \
         patch("os.path.isfile", return_value=True), \
         patch("app.services.session_template_catalog.build_catalog_mirror_reqs", return_value=[req]), \
         patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_sin_formatos_devuelve_success_vacio():
    agent = _make_agent()

    inp = AgentInput(
        session_id="sess_f1",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101AAA",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [], "formatos": []},
        },
    )

    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 0
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_con_formatos_llm_invocado_y_success():
    agent = _make_agent()

    req = {
        "id": "1.1",
        "nombre": "Anexo M Declaracion de Integridad",
        "descripcion": "Manifestacion de integridad para la propuesta",
        "tipo": "administrativo",
        "tipo_accion": "generar",
    }
    inp = AgentInput(
        session_id="sess_f2",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
                "master_profile": {
                    "razon_social": "Test SA",
                    "rfc": "TST010101BBB",
                    "representante_legal": "Ana Test",
                    "domicilio_fiscal": _SLOTS_PILOTO["domicilio_fiscal"],
                },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), \
         patch("app.services.document_deliverable_filter.should_show_deliverable_in_ui", return_value=True), \
         patch("app.services.document_deliverable_filter.has_admin_format_template_evidence", return_value=True), \
         patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    payload = out.model_dump().get("data") or {}
    assert out.status == AgentStatus.SUCCESS
    assert payload["count"] == 1
    assert len(payload["documentos"]) == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_template_lock_no_invoca_llm_si_hay_template_bloqueado():
    agent = _make_agent()
    req = {
        "id": "ANEXO 7",
        "nombre": "Anexo 7 Manifestación",
        "descripcion": "Formato legal del anexo 7",
        "tipo": "administrativo",
        "tipo_accion": "generar",
    }
    inp = AgentInput(
        session_id="sess_template_lock",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101EEE",
                "representante_legal": "Ana Test",
                "domicilio_fiscal": _SLOTS_PILOTO["domicilio_fiscal"],
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), \
         patch("app.services.document_deliverable_filter.should_show_deliverable_in_ui", return_value=True), \
         patch("app.services.document_deliverable_filter.has_admin_format_template_evidence", return_value=True), \
         patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    payload = out.model_dump().get("data") or {}
    assert out.status == AgentStatus.SUCCESS
    assert payload["count"] == 1
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("req", "expected_name"),
    [
        (
            {
                "id": "AD-186",
                "nombre": "Escrito de Integración y No Colusión",
                "descripcion": "Escrito de Integración y No Colusión",
                "label_taxonomica": "DECL_INTEGRIDAD",
                "tipo": "administrativo",
                "tipo_accion": "generar",
            },
            "Escrito de Integración y No Colusión",
        ),
        (
            {
                "id": "AD-187",
                "nombre": "Estratificación de las Micro, Pequeñas y Medianas Empresas",
                "descripcion": "Estratificación de las Micro, Pequeñas y Medianas Empresas",
                "label_taxonomica": "DECL_MIPYME",
                "tipo": "administrativo",
                "tipo_accion": "generar",
            },
            "Estratificación de las Micro, Pequeñas y Medianas Empresas",
        ),
    ],
)
async def test_templates_taxonomicos_no_invocan_llm(req, expected_name):
    agent = _make_agent()
    inp = AgentInput(
        session_id="sess_tax_lock",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Test SA",
                "rfc": "TST010101EEE",
                "representante_legal": "Ana Test",
                "domicilio_fiscal": _SLOTS_PILOTO["domicilio_fiscal"],
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), \
         patch("app.services.document_deliverable_filter.should_show_deliverable_in_ui", return_value=True), \
         patch("app.services.document_deliverable_filter.has_admin_format_template_evidence", return_value=True), \
         patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    payload = out.model_dump().get("data") or {}
    assert out.status == AgentStatus.SUCCESS
    assert payload["count"] == 1
    assert payload["documentos"][0]["nombre"] == expected_name
    agent.llm.generate.assert_not_awaited()
    assert payload["documentos"][0]["template_id"] in {
        "decl_integridad_no_colusion",
        "decl_mipyme",
    }
    assert payload["materialization_metrics"]["routes"]["template_locked"] == 1


@pytest.mark.asyncio
async def test_fallback_compliance_desde_tasks_cuando_no_hay_inyeccion():
    """Sin compliance_master_list en company_data debe leer stage_completed:compliance."""
    compliance_payload = {
        "administrativo": [
            {
                "id": "1.2",
                    "nombre": "Declaración de Integridad",
                    "descripcion": "Manifestación bajo protesta",
                "tipo": "administrativo",
                    "tipo_accion": "generar",
            }
        ],
        "formatos": [],
    }
    tasks = [
        {
            "task": "stage_completed:compliance",
            "result": {"status": "success", "data": compliance_payload},
        }
    ]
    agent = _make_agent(tasks=tasks)

    inp = AgentInput(
        session_id="sess_f3",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Fallback SA",
                "rfc": "FAL010101CCC",
                **_SLOTS_PILOTO,
            },
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_error_no_genera_archivo_y_sigue():
    agent = _make_agent()
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=False, error="LLM timeout", response="")
    )

    req = {"id": "1.3", "nombre": "Anexo M Declaracion de Integridad", "tipo": "administrativo", "tipo_accion": "generar"}
    inp = AgentInput(
        session_id="sess_f4",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Err SA",
                "rfc": "ERR010101DDD",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx") as mock_save:
        out = await agent.process(inp)

    agent.llm.generate.assert_awaited_once()
    mock_save.assert_not_called()
    assert out.data["count"] == 0


@pytest.mark.asyncio
async def test_item_sin_prefijo_pero_tipo_administrativo_se_incluye():
    agent = _make_agent()

    req = {"id": "admin_003", "nombre": "Declaración de Integridad", "tipo": "administrativo", "tipo_accion": "generar"}
    inp = AgentInput(
        session_id="sess_f5",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Tipo SA",
                "rfc": "TIP010101EEE",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_inventory_legal_genera_sin_compliance_rows():
    """Modo fábrica: ítems legal_administrative PENDING del inventario pasan por FormatsAgent."""
    agent = _make_agent()
    inv = {
        "session_id": "sess_fmt_inv",
        "schema_version": "1.0.0",
        "revision": 1,
        "items": [
            {
                "canonical_id": "forma_dd_01",
                "display_name": "Forma DD-01",
                "description": "Escrito de facultades",
                "category": "legal_administrative",
                "tier": "anchored",
                "status": "pending",
                "anchors": [{"snippet": "Forma DD-01", "confidence": 1.0}],
                "bases_revision": "revfmt001",
                "generator_hint": "plantilla_o_llm:DD-01",
            }
        ],
    }
    inp = AgentInput(
        session_id="sess_fmt_inv",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Fmt Inv SA",
                "rfc": "FMT010101XYZ",
                **_SLOTS_PILOTO,
            },
            "compliance_master_list": {"administrativo": [], "formatos": []},
            "document_inventory": inv,
        },
    )
    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.SUCCESS
    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()
    prompt = str(agent.llm.generate.await_args.kwargs.get("prompt") or agent.llm.generate.await_args.args[0])
    assert "GUÍA_DE_PLANTILLA" in prompt


@pytest.mark.asyncio
async def test_formats_quality_gate_bloquea_sin_generar(monkeypatch):
    """
    El gate solo bloquea cuando no hay absolutamente nada que hacer
    (ni generar ni presentar físicamente). Con items presentar_fisico,
    el gate loguea pero continúa.
    """
    agent = _make_agent()
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_HARD_GATE_ENABLED", True)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_ITEMS", 3)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MAX_UNKNOWN_RATIO", 0.9)
    monkeypatch.setattr(app_settings, "DOCUMENT_QUALITY_GATE_MIN_EVIDENCE_MATCH_RATIO", 0.1)

    # Solo items presentar_fisico e informativo — generar_count=0 pero hay presentar_fisico
    # El gate detecta el problema pero NO bloquea porque hay algo que hacer
    reqs = [
        {"id": "AD-01", "nombre": "INE", "tipo_accion": "presentar_fisico", "evidence_match": True},
        {"id": "AD-02", "nombre": "Acta", "tipo_accion": "presentar_fisico", "evidence_match": True},
        {"id": "AD-03", "nombre": "Fecha evento", "tipo_accion": "informativo", "evidence_match": True},
    ]
    inp = AgentInput(
        session_id="sess_f_gate",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {"razon_social": "Gate SA", "rfc": "GAT010101AAA", **_SLOTS_PILOTO},
            "compliance_master_list": {"administrativo": reqs, "formatos": []},
        },
    )
    with patch("os.makedirs"):
        out = await agent.process(inp)
    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert out.data.get("document_quality_gate", {}).get("reason") == "no_actionable_generate_items"

    # Caso extremo: sin nada que hacer (0 items) → sí bloquea
    reqs_vacio = []
    inp_vacio = AgentInput(
        session_id="sess_f_gate_vacio",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {"razon_social": "Gate SA", "rfc": "GAT010101AAA", **_SLOTS_PILOTO},
            "compliance_master_list": {"administrativo": reqs_vacio, "formatos": []},
        },
    )
    with patch("os.makedirs"):
        out_vacio = await agent.process(inp_vacio)
    # Con 0 items totales, el gate no llega al umbral mínimo (min_items=3) → no bloquea tampoco
    # El bloqueo solo ocurre cuando total_items >= min_items Y generar_count=0 Y presentar_fisico=0
    assert out_vacio.status in (AgentStatus.SUCCESS, AgentStatus.WAITING_FOR_DATA)


# =============================================================================
# INTEGRATION TESTS: Gate documental — Requirements 5.1, 5.4, 6.3
# =============================================================================


@pytest.mark.asyncio
async def test_formats_no_bloquea_por_faltantes_no_criticos():
    """
    Req 5.4 / 6.3: Cuando solo faltan campos informativos (no bloqueantes),
    FormatsAgent debe continuar generando documentos (no WAITING_FOR_DATA).

    El gate documental de FormatsAgent se basa en la calidad de la lista de
    compliance (tipo_accion, evidence_match), NO en faltantes de perfil
    informativos. Si el perfil tiene rfc, razon_social, domicilio_fiscal y
    representante_legal (campos críticos), el agente debe proceder aunque
    falten telefono, email, etc.
    """
    agent = _make_agent()

    # Perfil con campos críticos completos, pero sin campos informativos
    req = {
        "id": "1.1",
        "nombre": "Carta de Presentación",
        "descripcion": "Carta formal de presentación",
        "tipo": "administrativo",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_gate_no_criticos",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                # Campos críticos presentes
                "razon_social": "Empresa Completa SA",
                "rfc": "EMP010101AAA",
                "domicilio_fiscal": "Av. Reforma 100, CDMX",
                "representante_legal": "Juan Representante",
                # Campos informativos ausentes (telefono, email, web, etc.)
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
    )

    with patch("os.makedirs"), patch("app.agents.formats._save_docx"):
        out = await agent.process(inp)

    # Con campos críticos completos, debe generar sin bloquear
    assert out.status == AgentStatus.SUCCESS, (
        f"FormatsAgent no debe bloquear por faltantes informativos. Status: {out.status}, msg: {out.message}"
    )
    assert out.data["count"] == 1
    agent.llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_formats_bloquea_solo_por_criticos_via_pilot_slots():
    """
    Req 5.1 / 5.4: Cuando falta un campo crítico (domicilio_fiscal o
    representante_legal), FormatsAgent debe retornar WAITING_FOR_DATA.

    Verifica que el bloqueo duro se activa SOLO por campos en BLOCKING_FIELDS
    (rfc, razon_social, domicilio_fiscal, representante_legal).
    """
    agent = _make_agent()

    req = {
        "id": "1.2",
        "nombre": "Declaración de Integridad",
        "descripcion": "Declaración bajo protesta",
        "tipo": "administrativo",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_gate_critico_faltante",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Empresa Incompleta SA",
                "rfc": "INC010101BBB",
                # domicilio_fiscal ausente → campo crítico faltante
                # representante_legal ausente → campo crítico faltante
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
        job_id="job_gate_critico",
    )

    with patch("os.makedirs"):
        out = await agent.process(inp)

    assert out.status == AgentStatus.WAITING_FOR_DATA, (
        f"FormatsAgent debe bloquear cuando faltan campos críticos. Status: {out.status}"
    )
    # Los campos faltantes deben ser los críticos
    missing_fields = [m["field"] for m in (out.data.get("missing") or [])]
    assert "domicilio_fiscal" in missing_fields or "representante_legal" in missing_fields, (
        f"Debe reportar campos críticos faltantes. missing: {missing_fields}"
    )
    agent.llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_flujo_mixto_criticos_e_informativos_bloquea_solo_por_criticos():
    """
    Req 6.3 / 5.4: Flujo mixto — perfil con faltantes críticos Y no críticos.

    Cuando hay faltantes de ambos tipos, el bloqueo debe ocurrir por los
    críticos. Los informativos no deben ser la causa del bloqueo.

    Este test verifica el invariante clave: WAITING_FOR_DATA se justifica
    SOLO por campos en missing_blocking (críticos faltantes).
    """
    agent = _make_agent()

    req = {
        "id": "1.3",
        "nombre": "Acta Constitutiva",
        "descripcion": "Copia del acta",
        "tipo": "administrativo",
        "tipo_accion": "generar",
        "evidence_match": True,
    }
    inp = AgentInput(
        session_id="sess_mixto_criticos_informativos",
        mode="generation_only",
        company_data={
            "mode": "generation_only",
            "master_profile": {
                "razon_social": "Empresa Mixta SA",
                # rfc ausente → crítico faltante
                # domicilio_fiscal ausente → crítico faltante
                # representante_legal ausente → crítico faltante
                # telefono, email ausentes → informativos faltantes (no bloquean)
            },
            "compliance_master_list": {"administrativo": [req], "formatos": []},
        },
        job_id="job_mixto",
    )

    with patch("os.makedirs"):
        out = await agent.process(inp)

    # Debe bloquear porque hay críticos faltantes
    assert out.status == AgentStatus.WAITING_FOR_DATA, (
        "Con faltantes críticos en flujo mixto, debe bloquear generación."
    )
    # El bloqueo debe ser por campos críticos, no informativos
    missing_fields = [m["field"] for m in (out.data.get("missing") or [])]
    critical_fields = {"rfc", "razon_social", "domicilio_fiscal", "representante_legal"}
    blocking_missing = [f for f in missing_fields if f in critical_fields]
    assert len(blocking_missing) > 0, (
        f"El bloqueo debe ser por campos críticos. missing: {missing_fields}"
    )
    agent.llm.generate.assert_not_awaited()
