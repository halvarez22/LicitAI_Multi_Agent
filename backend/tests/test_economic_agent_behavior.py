"""
EconomicAgent: contrato de entrada/salida y ramas sin llamar a Ollama (LLM mockeado).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.economic import EconomicAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.economic_validation.models import EconomicValidationResult
from app.services.resilient_llm import LLMResponse


def _memory_stub(session: dict | None = None, company: dict | None = None):
    mem = AsyncMock()
    sess = session if session is not None else {"tasks_completed": []}
    comp = company if company is not None else None
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.get_company = AsyncMock(return_value=comp)
    mem.get_line_items_for_session = AsyncMock(return_value=[])
    mem.replace_line_items_for_document = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem


def _agent_input(
    session_id: str,
    *,
    company_id=None,
    compliance_master_list=None,
) -> AgentInput:
    data = {}
    if compliance_master_list is not None:
        data["compliance_master_list"] = compliance_master_list
    return AgentInput(session_id=session_id, company_id=company_id, company_data=data)


@pytest.mark.asyncio
async def test_sin_requisitos_tecnico_devuelve_success_sin_llm():
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)

    with patch.object(agent, "llm") as mock_llm:
        out = await agent.process(
            _agent_input(
                "s1",
                compliance_master_list={
                    "administrativo": [{"x": 1}],
                    "tecnico": [],
                },
            )
        )
        mock_llm.generate.assert_not_called()

    assert out.status == AgentStatus.SUCCESS
    assert out.message and "No hay" in out.message


@pytest.mark.asyncio
async def test_con_tecnico_y_llm_matched_devuelve_success_con_data():
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)

    payload = '{"items": [{"concepto": "Luminaria LED", "cantidad": 2, "precio_unitario": 100.0, "subtotal": 200.0, "status": "matched"}], "alertas": ["Todo OK"]}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s2",
                company_id="co_x",
                compliance_master_list={
                    "tecnico": [{"descripcion": "Luminaria LED", "page": 1}]
                },
            )
        )

    assert out.status == AgentStatus.SUCCESS
    assert out.data["grand_total"] == pytest.approx(230.0)
    assert out.data["items"][0]["status"] == "matched"
    mock_llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_price_missing_devuelve_waiting_for_data():
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)

    payload = '{"items": [{"concepto": "X", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "price_missing"}]}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s3",
                company_id="co_x",
                compliance_master_list={"tecnico": [{"id": "t1"}]},
            )
        )

    assert out.status == AgentStatus.WAITING_FOR_DATA
    missing = out.data.get("missing", [])
    assert len(missing) == 1
    assert missing[0].get("type") == "economic_price"


@pytest.mark.asyncio
async def test_parser_correcto_mantiene_items_y_alertas_al_recibir_objeto():
    """Valida el fix del parser que ahora respeta objetos con {"items": [...]}."""
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)

    payload = '{"items": [{"concepto": "A", "cantidad": 1, "precio_unitario": 10, "subtotal": 10, "status": "matched"}], "alertas": []}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s5",
                compliance_master_list={"tecnico": [{"a": 1}]},
            )
        )

    assert out.status == AgentStatus.SUCCESS
    assert len(out.data["items"]) == 1
    assert out.data["items"][0]["status"] == "matched"


@pytest.mark.asyncio
async def test_llm_json_ilegible_propaga_items_vacios_como_success():
    """Documenta comportamiento actual: parse fallido -> [] -> totales 0 y success."""
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response="NO ES JSON")
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s4",
                compliance_master_list={"tecnico": [{"a": 1}]},
            )
        )

    assert out.status == AgentStatus.SUCCESS
    assert out.data["items"] == []
    assert out.data["grand_total"] == 0


@pytest.mark.asyncio
async def test_economic_agent_llm_error_devuelve_status_error():
    """Valida el fail-fast: si el LLM falla, el agente económico no finge propuesta vacía, retorna error."""
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(
                success=False, error="LLM timeout simulated", response=""
            )
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s_err",
                company_id="co_err",
                compliance_master_list={"tecnico": [{"desc": "Licitación"}]},
            )
        )

    assert out.status == AgentStatus.ERROR
    assert out.error and "LLM timeout simulated" in out.error
    mock_llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_economic_agent_usa_catalogo_de_empresa_real():
    """Hito 2: Verifica que el agente lea el catálogo persistido (vía adaptador Postgres)."""
    mock_catalog = [{"concepto": "Servidor Dell R740", "precio_unitario": 150000.0}]
    mem = _memory_stub(
        company={
            "id": "co_tec",
            "name": "Tecnología Avanzada",
            "catalog": mock_catalog,
        }
    )

    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    payload = '{"items": [{"concepto": "Servidor Dell R740", "cantidad": 1, "precio_unitario": 150000.0, "subtotal": 150000.0, "status": "matched"}]}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})

        out = await agent.process(
            _agent_input(
                "sess-catalog-test",
                company_id="co_tec",
                compliance_master_list={
                    "tecnico": [{"descripcion": "1 Servidor tipo rack", "page": 4}]
                },
            )
        )

    assert out.status == AgentStatus.SUCCESS
    assert out.data["items"][0]["precio_unitario"] == 150000.0
    assert out.data["items"][0]["status"] == "matched"

    mem.get_company.assert_awaited_with("co_tec")

    call_args = mock_llm.generate.call_args[1]
    assert "Servidor Dell R740" in call_args["prompt"]
    assert "150000" in call_args["prompt"]


@pytest.mark.asyncio
async def test_prompt_incluye_reglas_y_alcance_del_analista():
    """El LLM recibe bloque de contexto y el catálogo incluye filas de alcance_operativo."""
    sess = {
        "tasks_completed": [
            {
                "task": "analisis_bases",
                "result": {
                    "reglas_economicas": {"meses_o_periodo_minimo_citado": "6 meses"},
                    "alcance_operativo": [
                        {
                            "ubicacion_o_area": "Norte",
                            "puesto_funcion_o_servicio": "Vigilante",
                            "cantidad_o_elementos": "3",
                            "texto_literal_fila": "Turno 12h",
                        }
                    ],
                    "datos_tabulares": {
                        "line_items_count": 2,
                        "texto_sugiere_partidas_o_anexo_tabular": False,
                        "senal_tabular_coincidencias": 0,
                        "alerta_faltante": None,
                    },
                },
            }
        ]
    }
    mem = _memory_stub(session=sess)
    ctx = MCPContextManager(mem)

    payload = '{"items": [{"concepto": "Vigilante", "cantidad": 3, "precio_unitario": 50, "subtotal": 150, "status": "matched"}], "alertas": []}'

    mock_vec = MagicMock()
    mock_vec.query_texts = MagicMock(return_value={"documents": []})
    with (
        patch("app.agents.economic.VectorDbServiceClient", return_value=mock_vec),
        patch(
            "app.agents.economic.validate_economic_proposal",
            return_value=EconomicValidationResult(perfil_usado="generic"),
        ),
    ):
        agent = EconomicAgent(ctx)
        with patch.object(agent, "llm") as mock_llm:
            mock_llm.generate = AsyncMock(
                return_value=LLMResponse(success=True, response=payload)
            )
            out = await agent.process(
                _agent_input(
                    "s-alcance",
                    company_id="co_x",
                    compliance_master_list={
                        "tecnico": [{"descripcion": "Vigilante", "id": "t1"}]
                    },
                )
            )

    assert out.status == AgentStatus.SUCCESS
    prompt = mock_llm.generate.call_args[1]["prompt"]
    assert "meses_o_periodo_minimo_citado" in prompt or "6 meses" in prompt
    assert "Vigilante" in prompt
    assert "is_alcance_operativo" in prompt or "Alcance operativo" in prompt
    assert out.data.get("contexto_bases_analista", {}).get("alcance_operativo_filas") == 1


@pytest.mark.asyncio
async def test_alertas_contexto_bases_en_salida_y_waiting():
    """datos_tabulares.alerta_faltante y reglas no default pasan a analisis_precios / data."""
    sess = {
        "tasks_completed": [
            {
                "task": "analisis_bases",
                "result": {
                    "reglas_economicas": {
                        "criterio_importe_minimo_o_plazo_inferior": "100000 MXN"
                    },
                    "alcance_operativo": [],
                    "datos_tabulares": {
                        "line_items_count": 0,
                        "texto_sugiere_partidas_o_anexo_tabular": True,
                        "senal_tabular_coincidencias": 2,
                        "alerta_faltante": "Ingerir Excel de partidas.",
                    },
                },
            }
        ]
    }
    mem = _memory_stub(session=sess)
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    ok_payload = '{"items": [{"concepto": "A", "cantidad": 1, "precio_unitario": 10, "subtotal": 10, "status": "matched"}], "alertas": ["LLM ok"]}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=ok_payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out_ok = await agent.process(
            _agent_input(
                "s-alert-ok",
                compliance_master_list={"tecnico": [{"a": 1}]},
            )
        )

    assert out_ok.status == AgentStatus.SUCCESS
    alerts = out_ok.data["analisis_precios"]["alertas"]
    assert any("Ingerir Excel" in a for a in alerts)
    assert any("criterio_importe_minimo" in a for a in alerts)

    gap_payload = '{"items": [{"concepto": "X", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "price_missing"}]}'
    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=gap_payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out_w = await agent.process(
            _agent_input(
                "s-alert-wait",
                compliance_master_list={"tecnico": [{"id": "t1"}]},
            )
        )

    assert out_w.status == AgentStatus.WAITING_FOR_DATA
    acb = out_w.data.get("alertas_contexto_bases", [])
    assert any("Ingerir Excel" in a for a in acb)
