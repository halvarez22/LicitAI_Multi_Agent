"""
EconomicAgent: contrato de entrada/salida y ramas sin llamar a Ollama (LLM mockeado).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.economic import EconomicAgent, _human_economic_blocking_summary
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.economic_validation.models import EconomicValidationResult
from app.services.resilient_llm import LLMResponse


def _memory_stub(
    session: dict | None = None,
    company: dict | None = None,
    line_items: list[dict] | None = None,
):
    mem = AsyncMock()
    sess = session if session is not None else {"tasks_completed": []}
    comp = company if company is not None else None
    litems = line_items if line_items is not None else []
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.get_company = AsyncMock(return_value=comp)
    mem.get_line_items_for_session = AsyncMock(return_value=litems)
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
    assert out.data["grand_total"] == pytest.approx(232.0)
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
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t1",
                            "descripcion": "Seguro requerido",
                            "source": "bases.pdf",
                            "page": 33,
                            "snippet": "Se solicita seguro con cobertura mínima",
                        }
                    ]
                },
            )
        )

    assert out.status == AgentStatus.WAITING_FOR_DATA


@pytest.mark.asyncio
async def test_economic_silence_ignora_legales_inferidos_no_bloqueantes():
    sess = {
        "document_inventory": {
            "items": [
                {
                    "category": "legal_administrative",
                    "status": "pending",
                    "tier": "inferred",
                    "is_blocking": False,
                    "display_name": "Acta de Fallo",
                }
            ]
        }
    }
    ctx = MCPContextManager(_memory_stub(session=sess))
    agent = EconomicAgent(ctx)
    assert await agent._check_economic_silence("s-silence-off", "corr-1") is False


@pytest.mark.asyncio
async def test_economic_silence_si_hay_legal_bloqueante_pendiente():
    sess = {
        "document_inventory": {
            "items": [
                {
                    "category": "legal_administrative",
                    "status": "pending",
                    "tier": "required",
                    "is_blocking": True,
                    "display_name": "Documento legal crítico",
                }
            ]
        }
    }
    ctx = MCPContextManager(_memory_stub(session=sess))
    agent = EconomicAgent(ctx)
    assert await agent._check_economic_silence("s-silence-on", "corr-2") is True


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
async def test_llm_json_ilegible_items_vacios_bloquea_total_base_cotizable():
    """Parse fallido -> sin partidas / total 0: debe pausar (regla total_base_cotizable), no SUCCESS."""
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

    assert out.status == AgentStatus.WAITING_FOR_DATA
    vres = out.data.get("validation_result") or {}
    issues = " ".join(vres.get("blocking_issues") or [])
    assert "total_base_cotizable" in issues


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
async def test_quadrature_delta_mayor_a_un_centavo_bloquea_generacion():
    """Si subtotal tabular y cantidad×PU no cuadran, el agente detiene."""
    mem = _memory_stub(
        line_items=[
            {
                "concepto_norm": "vigilante",
                "concepto_raw": "Vigilante",
                "cantidad": 1,
                "precio_unitario": 120.00,
                "subtotal": 150.00,
            }
        ]
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = '{"items": [{"concepto": "Vigilante", "cantidad": 1, "precio_unitario": 120.0, "subtotal": 120.0, "status": "matched"}], "alertas": []}'
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
                "s-quadrature-block",
                compliance_master_list={"tecnico": [{"id": "t1", "descripcion": "Vigilante"}]},
            )
        )
    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert "cuadratura" in str(out.message or "").lower()
    qr = out.data.get("quadrature_report") or {}
    assert qr.get("available") is True
    assert qr.get("blocking") is True


@pytest.mark.asyncio
async def test_quadrature_extrema_prefiere_session_line_items_canonicos():
    """Si el LLM resume mal y la base tabular de sesión es mas rica, se usa la verdad canónica."""
    mem = _memory_stub(
        line_items=[
            {
                "concepto_norm": "umaps atarjea",
                "concepto_raw": "UMAPS ATARJEA",
                "cantidad": None,
                "precio_unitario": 2.0,
                "subtotal": None,
                "importe": None,
            },
            {
                "concepto_norm": "umaps doctor mora",
                "concepto_raw": "UMAPS DOCTOR MORA",
                "cantidad": None,
                "precio_unitario": 6.0,
                "subtotal": None,
                "importe": None,
            },
            {
                "concepto_norm": "caises san jose iturbide",
                "concepto_raw": "CAISES SAN JOSÉ ITURBIDE",
                "cantidad": None,
                "precio_unitario": 4.0,
                "subtotal": None,
                "importe": None,
            },
        ]
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = '{"items": [{"concepto": "Resumen parcial", "cantidad": 1, "precio_unitario": 35.0, "subtotal": 35.0, "status": "matched"}], "alertas": []}'
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
                "s-quadrature-canonical",
                compliance_master_list={"tecnico": [{"id": "t1", "descripcion": "Servicio de limpieza"}]},
            )
        )
    assert out.status == AgentStatus.SUCCESS
    qr = out.data.get("quadrature_report") or {}
    assert qr.get("available") is True
    assert qr.get("blocking") is False
    assert qr.get("engine_total") == pytest.approx(12.0)
    assert qr.get("excel_total") == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_health_profile_sin_parametros_fsr_bloquea():
    """Perfiles salud deben fallar cerrado si faltan parámetros FSR."""
    mem = _memory_stub()
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = '{"items": [{"concepto": "Servicio X", "cantidad": 1, "precio_unitario": 100.0, "subtotal": 100.0, "status": "matched"}], "alertas": []}'
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
                "s-salario-real-block",
                compliance_master_list={"tecnico": [{"id": "t1", "descripcion": "Servicio X"}]},
            )
        )
    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert "factor de salario real" in str(out.message or "").lower()
    calc = out.data.get("calculator_result") or {}
    assert "salario_real_v1" in str(calc.get("formula_set") or "")


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
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t1",
                            "descripcion": "Servicio X",
                            "source": "bases.pdf",
                            "page": 28,
                            "snippet": "Partida con precio unitario obligatorio",
                        }
                    ]
                },
            )
        )

    assert out_w.status == AgentStatus.WAITING_FOR_DATA
    acb = out_w.data.get("alertas_contexto_bases", [])
    assert any("Ingerir Excel" in a for a in acb)


@pytest.mark.asyncio
async def test_calculate_proposal_prompt_prohibe_documentales():
    ctx = MCPContextManager(_memory_stub())
    agent = EconomicAgent(ctx)
    with patch.object(agent, "llm") as mock_llm:
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response='{"items":[],"alertas":[]}')
        )
        await agent._calculate_proposal(
            requirements=[{"id": "t1", "descripcion": "Escrito bajo protesta"}],
            catalog=[],
            correlation_id="corr-test",
            bases_economic_context="",
        )
        called_prompt = mock_llm.generate.await_args.kwargs.get("prompt", "")
        assert "NO cotices entregables documentales/legales" in called_prompt


@pytest.mark.asyncio
async def test_non_cotizable_override_no_reemite_gap():
    sess = {
        "economic_non_cotizable_overrides": [
            {"field": "price_t1", "reason": "user_marked_non_cotizable_documental"}
        ],
        "tasks_completed": [],
    }
    mem = _memory_stub(session=sess)
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    payload = '{"items": [{"concepto": "Seguros", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "price_missing"}]}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch(
            "app.agents.economic.validate_economic_proposal",
            return_value=EconomicValidationResult(perfil_usado="generic"),
        ),
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-noncot",
                company_id="co_x",
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t1",
                            "descripcion": "Seguros",
                            "source": "bases.pdf",
                            "page": 45,
                            "snippet": "Cobertura de seguros solicitada en el pliego",
                        }
                    ]
                },
            )
        )

    assert out.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_fail_closed_no_emite_gap_sin_ancla_y_registra_limbo():
    sess = {"tasks_completed": []}
    mem = _memory_stub(session=sess)
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    payload = '{"items": [{"concepto": "Seguros", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "price_missing"}]}'

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch(
            "app.agents.economic.validate_economic_proposal",
            return_value=EconomicValidationResult(perfil_usado="generic"),
        ),
    ):
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(success=True, response=payload)
        )
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-fail-closed",
                company_id="co_x",
                compliance_master_list={"tecnico": [{"id": "t1", "descripcion": "Seguros sin ancla"}]},
            )
        )

    assert out.status == AgentStatus.SUCCESS
    assert mem.save_session.await_count >= 1


@pytest.mark.asyncio
async def test_validation_blocking_emite_blocking_items_accionables():
    mem = _memory_stub(session={"tasks_completed": []})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = '{"items": [{"concepto": "Guardia", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"}], "alertas": []}'

    vr = EconomicValidationResult(
        perfil_usado="generic",
        blocking_issues=["economic_validation_blocking: 2 items con precio <= 0"],
        trazabilidad={
            "economic_validation_blocking": {
                "valor_calculado": ["Guardia diurna", "Guardia nocturna"]
            }
        },
    )
    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch("app.agents.economic.validate_economic_proposal", return_value=vr),
        patch("app.agents.economic.logger") as mock_logger,
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-block-items",
                company_id="co_x",
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t1",
                            "descripcion": "Guardia",
                            "source": "bases.pdf",
                            "page": 12,
                            "snippet": "Se requiere servicio de guardia",
                        }
                    ]
                },
            )
        )
        log_calls = [c for c in mock_logger.info.call_args_list if c.args and c.args[0] == "economic_proposal_blocking_persisted"]
        assert log_calls, "debe emitirse economic_proposal_blocking_persisted antes de persistir la tarea"
        kw = log_calls[0].kwargs
        assert kw.get("blocking_issues_count") == 1
        assert kw.get("validation_events_count") >= 1
        assert kw.get("missing_pending_count") >= 1
        assert kw.get("perfil_usado") == "generic"
    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing", [])
    assert miss and miss[0].get("type") == "economic_validation_blocking"
    bi = miss[0].get("blocking_items") or []
    assert len(bi) >= 1
    # El chatbot y servicios leen validation_result desde tasks_completed → economic_proposal.
    persisted = False
    for aw in mem.save_session.await_args_list:
        args = getattr(aw, "args", None)
        if not args or len(args) < 2 or not isinstance(args[1], dict):
            continue
        for t in args[1].get("tasks_completed") or []:
            if t.get("task") != "economic_proposal":
                continue
            res = t.get("result") or {}
            vr = res.get("validation_result") or {}
            if vr.get("blocking_issues") and res.get("status") == "waiting_for_data":
                persisted = True
                break
    assert persisted, "Debe persistirse economic_proposal con validation_result al bloquear por validación"


@pytest.mark.asyncio
async def test_validation_blocking_fallback_desde_proposal_si_trazabilidad_vacia():
    """Si validation_result no trae nombres en trazabilidad, se deriva blocking_items desde proposal_draft."""
    mem = _memory_stub(session={"tasks_completed": []})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = '{"items": [{"concepto": "Limpieza de vidrios", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"}], "alertas": []}'

    vr = EconomicValidationResult(
        perfil_usado="generic",
        blocking_issues=["precios_positivos: 1 ítems con precio <= 0"],
        trazabilidad={"precios_positivos": {"valor_calculado": []}},
    )
    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch("app.agents.economic.validate_economic_proposal", return_value=vr),
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-block-fallback-proposal",
                company_id="co_x",
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t1",
                            "descripcion": "Limpieza de vidrios",
                            "source": "bases.pdf",
                            "page": 10,
                            "snippet": "Servicio de limpieza de vidrios",
                        }
                    ]
                },
            )
        )
    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing", [])
    assert miss and miss[0].get("type") == "economic_validation_blocking"
    bi = miss[0].get("blocking_items") or []
    assert bi and "limpieza de vidrios" in str(bi[0].get("concepto_label") or "").lower()


@pytest.mark.asyncio
async def test_validation_blocking_precios_positivos_no_colapsa_a_n_partidas():
    """Con múltiples conceptos en trazabilidad, el primer blocking_item debe ser concepto real."""
    mem = _memory_stub(session={"tasks_completed": []})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = (
        '{"items": ['
        '{"concepto": "Servicio de vigilancia A", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"},'
        '{"concepto": "Servicio de vigilancia B", "concepto_id": "t2", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"}'
        '], "alertas": []}'
    )
    vr = EconomicValidationResult(
        perfil_usado="generic",
        blocking_issues=["precios_positivos: 3 ítems con precio <= 0"],
        trazabilidad={
            "precios_positivos": {
                "valor_calculado": [
                    "Servicio de vigilancia A",
                    "Servicio de vigilancia B",
                    "Servicio de vigilancia C",
                ]
            }
        },
    )
    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch("app.agents.economic.validate_economic_proposal", return_value=vr),
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-block-multi",
                company_id="co_x",
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t1",
                            "descripcion": "Servicio de vigilancia A",
                            "source": "bases.pdf",
                            "page": 21,
                            "snippet": "Servicio de vigilancia A requerido por la convocante.",
                        }
                    ]
                },
            )
        )
    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing", [])
    bi = (miss[0].get("blocking_items") if miss else []) or []
    assert bi
    first = str(bi[0].get("concepto_label") or "").lower()
    assert "partidas" not in first and "conceptos" not in first
    assert "servicio de vigilancia a" in first or ("item #1" in first or "ítem #1" in first)


@pytest.mark.asyncio
async def test_validation_blocking_excluye_items_sin_page_ni_row():
    """Contrato de evidencia: un ítem sin page_number ni row_index no debe exponerse al chat."""
    mem = _memory_stub(session={"tasks_completed": []})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = '{"items": [{"concepto": "Frecuencias y rutinas del servicio", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"}], "alertas": []}'
    vr = EconomicValidationResult(
        perfil_usado="generic",
        blocking_issues=["precios_positivos: 1 ítems con precio <= 0"],
        trazabilidad={"precios_positivos": {"valor_calculado": ["Frecuencias y rutinas del servicio"]}},
    )
    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch("app.agents.economic.validate_economic_proposal", return_value=vr),
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-block-no-locator",
                company_id="co_x",
                compliance_master_list={"tecnico": [{"id": "t1", "descripcion": "Frecuencias y rutinas del servicio"}]},
            )
        )
    assert out.status == AgentStatus.WAITING_FOR_DATA
    assert out.data.get("missing") == []
    assert "error de extracción" in str(out.message or "").lower()


@pytest.mark.asyncio
async def test_validation_blocking_excluye_documentales_como_repse():
    """Cortafuego: términos documentales (p.ej. REPSE/registro) no se piden como precio."""
    mem = _memory_stub(session={"tasks_completed": []})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = (
        '{"items": ['
        '{"concepto": "Registro de prestadores de servicios especializados u obras especializadas (REPSE)", "concepto_id": "t1", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"},'
        '{"concepto": "Servicio de vigilancia turno diurno", "concepto_id": "t2", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "matched"}'
        '], "alertas": []}'
    )
    vr = EconomicValidationResult(
        perfil_usado="generic",
        blocking_issues=["precios_positivos: 2 ítems con precio <= 0"],
        trazabilidad={
            "precios_positivos": {
                "valor_calculado": [
                    "Registro de prestadores de servicios especializados u obras especializadas (REPSE)",
                    "Servicio de vigilancia turno diurno",
                ]
            }
        },
    )
    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch("app.agents.economic.validate_economic_proposal", return_value=vr),
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-block-no-repse",
                company_id="co_x",
                compliance_master_list={
                    "tecnico": [
                        {"id": "t1", "descripcion": "REPSE vigente", "source": "bases.pdf", "page": 25, "snippet": "presentar REPSE"},
                        {"id": "t2", "descripcion": "Servicio de vigilancia turno diurno", "source": "bases.pdf", "page": 30, "snippet": "servicio de vigilancia turno diurno"},
                    ]
                },
            )
        )
    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing", [])
    bi = (miss[0].get("blocking_items") if miss else []) or []
    labels = " | ".join(str(x.get("concepto_label") or "").lower() for x in bi)
    assert "repse" not in labels and "registro" not in labels
    assert "vigilancia" in labels


@pytest.mark.asyncio
async def test_save_pending_questions_reemplaza_bloqueo_economico_previo():
    """Nueva corrida de bloqueo económico debe sustituir cola previa del mismo tipo (evita 3 vs 12)."""
    mem = _memory_stub(
        session={
            "tasks_completed": [],
            "pending_questions": [
                {"field": "validation_rule_1", "type": "economic_validation_blocking", "question": "12 ítems"},
                {"field": "validation_rule_2", "type": "economic_validation_blocking", "question": "12 ítems"},
                {"field": "price_x", "type": "economic_price", "question": "precio x"},
            ],
            "current_question_index": 2,
        }
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    await agent._save_pending_questions(
        "s-queue-replace",
        [
            {
                "field": "validation_rule_1",
                "label": "Corregir propuesta económica",
                "question": "3 ítems con precio <= 0",
                "type": "economic_validation_blocking",
                "blocking_items": [{"concepto_label": "Concepto A"}],
            }
        ],
    )
    saved = mem.save_session.await_args.args[1]
    pending = saved.get("pending_questions") or []
    assert len([q for q in pending if str(q.get("type")) == "economic_validation_blocking"]) == 1
    assert any(str(q.get("question") or "").startswith("3 ítems") for q in pending)


@pytest.mark.asyncio
async def test_save_pending_questions_reemplaza_economic_price_previas():
    """Nueva corrida de economic_price debe sustituir la cola previa para refrescar wording/procedencia."""
    mem = _memory_stub(
        session={
            "tasks_completed": [],
            "pending_questions": [
                {"field": "price_x", "type": "economic_price", "question": "vieja x"},
                {"field": "price_y", "type": "economic_price", "question": "vieja y"},
                {"field": "profile_conflict_1", "type": "evidence_profile_conflict", "question": "conflicto"},
            ],
            "current_question_index": 1,
        }
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    await agent._save_pending_questions(
        "s-queue-replace-price",
        [
            {
                "field": "price_x",
                "label": "Precio X",
                "question": "nueva x con procedencia",
                "type": "economic_price",
            },
            {
                "field": "price_z",
                "label": "Precio Z",
                "question": "nueva z con procedencia",
                "type": "economic_price",
            },
        ],
    )
    saved = mem.save_session.await_args.args[1]
    pending = saved.get("pending_questions") or []
    econ = [q for q in pending if str(q.get("type")) == "economic_price"]
    assert [q.get("field") for q in econ] == ["price_x", "price_z"]
    assert all("nueva" in str(q.get("question") or "") for q in econ)
    assert any(str(q.get("type")) == "evidence_profile_conflict" for q in pending)
    assert saved.get("current_question_index") == 0


@pytest.mark.asyncio
async def test_no_cotizable_items_but_price_source_docs_emits_waiting_for_data():
    """Si solo quedan anexos tipo catálogo/análisis de precios, debe pedir la fuente económica real."""
    mem = _memory_stub(company={"id": "co_ps", "master_profile": {"catalog": []}})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    out = await agent.process(
        _agent_input(
            "s-price-source",
            company_id="co_ps",
            compliance_master_list={
                "tecnico": [
                    {
                        "id": "t1",
                        "descripcion": "Catálogo de conceptos con cantidades y precios unitarios",
                        "source": "bases_isapeg.pdf",
                        "page": 3,
                        "snippet": "Presentar catálogo de conceptos con cantidades y precios unitarios.",
                    },
                    {
                        "id": "t2",
                        "descripcion": "Análisis de precios unitarios",
                        "source": "bases_isapeg.pdf",
                        "page": 3,
                        "snippet": "Integrar análisis de precios unitarios por concepto.",
                    },
                ]
            },
        )
    )

    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing") or []
    assert miss and miss[0].get("type") == "economic_validation_blocking"
    assert miss[0].get("input_mode") == "price_source"
    labels = " | ".join(str(x.get("concepto_label") or "").lower() for x in (miss[0].get("blocking_items") or []))
    assert "catálogo de conceptos" in labels or "catalogo de conceptos" in labels
    assert "análisis de precios" in labels or "analisis de precios" in labels
    assert "fuente real de precios" in str(out.message or "").lower()


@pytest.mark.asyncio
async def test_unanchored_gaps_with_price_source_docs_fallback_to_price_source():
    """Si los conceptos cotizables quedan sin ancla estricta, debe pedir catálogo/análisis real."""
    mem = _memory_stub(company={"id": "co_ps2", "master_profile": {"catalog": []}})
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = (
        '{"items": ['
        '{"concepto": "Costo indirecto", "concepto_id": "t_serv", "cantidad": 1, "precio_unitario": 0, "subtotal": 0, "status": "price_missing"}'
        '], "alertas": []}'
    )

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch(
            "app.agents.economic.validate_economic_proposal",
            return_value=EconomicValidationResult(perfil_usado="generic"),
        ),
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-price-source-fallback",
                company_id="co_ps2",
                compliance_master_list={
                    "tecnico": [
                        {"id": "t_serv", "descripcion": "Servicio principal sin ancla verificable"},
                        {
                            "id": "t_doc_1",
                            "descripcion": "Catálogo de conceptos con cantidades y precios unitarios",
                            "source": "bases_isapeg.pdf",
                            "page": 3,
                            "snippet": "Presentar catálogo de conceptos con cantidades y precios unitarios.",
                        },
                        {
                            "id": "t_doc_2",
                            "descripcion": "Análisis de precios unitarios",
                            "source": "bases_isapeg.pdf",
                            "page": 3,
                            "snippet": "Integrar análisis de precios unitarios por concepto.",
                        },
                    ]
                },
            )
        )

    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing") or []
    assert miss and miss[0].get("input_mode") == "price_source"
    assert miss[0].get("type") == "economic_validation_blocking"


@pytest.mark.asyncio
async def test_price_source_message_mentions_detected_zone_structure():
    """Si ya hay anexos tabulares con cantidades, el mensaje debe reconocer esa estructura."""
    mem = _memory_stub(
        company={"id": "co_ps3", "master_profile": {"catalog": []}},
        line_items=[
            {
                "id": "li-1",
                "document_id": "doc-a",
                "concepto_raw": "CAISES GUANAJUATO",
                "concepto_norm": "caises guanajuato",
                "unidad": "ELEMENTO",
                "cantidad": 6,
                "precio_unitario": 0.0,
                "sheet_name": "PARTIDA 1 ZONA A",
                "row_index": 11,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "service_zone_elements",
                    "zone": "A",
                },
            },
            {
                "id": "li-2",
                "document_id": "doc-a2",
                "concepto_raw": "BOLSA DE PLÁSTICO",
                "concepto_norm": "bolsa de plástico",
                "unidad": "KILO",
                "cantidad": 1528,
                "precio_unitario": 0.0,
                "sheet_name": "PARTIDA 2 ZONA A",
                "row_index": 3,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "monthly_material_requirement",
                },
            },
        ],
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    out = await agent.process(
        _agent_input(
            "s-price-source-structure",
            company_id="co_ps3",
            compliance_master_list={
                "tecnico": [
                    {
                        "id": "t1",
                        "descripcion": "Catálogo de conceptos con cantidades y precios unitarios",
                        "source": "bases_isapeg.pdf",
                        "page": 3,
                        "snippet": "Presentar catálogo de conceptos con cantidades y precios unitarios.",
                    },
                ]
            },
        )
    )

    assert out.status == AgentStatus.WAITING_FOR_DATA
    text = str(out.message or "").lower()
    assert "zona a" in text
    assert "6 elementos" in text
    assert "materiales" in text


@pytest.mark.asyncio
async def test_price_source_structure_summary_dedupes_repeated_service_rows():
    """Si la misma Partida 1 viene duplicada en dos anexos, el resumen no debe duplicar elementos."""
    repeated_line = {
        "concepto_raw": "CAISES GUANAJUATO",
        "concepto_norm": "caises guanajuato",
        "unidad": "ELEMENTO",
        "cantidad": 6,
        "precio_unitario": 0.0,
        "extra": {
            "layout": "structured_template",
            "template_kind": "service_zone_elements",
            "zone": "A",
            "site_code": "LIAI-001",
            "schedule": "LUNES A VIERNES (8 HORAS)",
        },
    }
    mem = _memory_stub(
        company={"id": "co_ps4", "master_profile": {"catalog": []}},
        line_items=[
            {"id": "li-1", "document_id": "doc-a1", "sheet_name": "PARTIDA 1 ZONA A", "row_index": 11, **repeated_line},
            {"id": "li-2", "document_id": "doc-a2", "sheet_name": "ANEXO III ZONA A", "row_index": 3, **repeated_line},
        ],
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    out = await agent.process(
        _agent_input(
            "s-price-source-dedupe",
            company_id="co_ps4",
            compliance_master_list={
                "tecnico": [
                    {
                        "id": "t1",
                        "descripcion": "Catálogo de conceptos con cantidades y precios unitarios",
                        "source": "bases_isapeg.pdf",
                        "page": 3,
                        "snippet": "Presentar catálogo de conceptos con cantidades y precios unitarios.",
                    },
                ]
            },
        )
    )

    assert out.status == AgentStatus.WAITING_FOR_DATA
    text = str(out.message or "").lower()
    assert "6 elementos" in text
    assert "12 elementos" not in text


@pytest.mark.asyncio
async def test_structured_slots_replace_generic_price_source_blocking():
    """Si ya existen anexos estructurados, debe pedir precios concretos en vez de `price_source` genérico."""
    mem = _memory_stub(
        company={"id": "co_ps5", "master_profile": {"catalog": []}},
        line_items=[
            {
                "id": "li-svc-a",
                "document_id": "doc-svc-a",
                "concepto_raw": "CAISES GUANAJUATO",
                "concepto_norm": "caises guanajuato",
                "unidad": "ELEMENTO",
                "cantidad": 6,
                "precio_unitario": 0.0,
                "sheet_name": "PARTIDA 1 ZONA A",
                "row_index": 11,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "service_zone_elements",
                    "zone": "A",
                    "schedule": "LUNES A VIERNES (8 HORAS)",
                    "source_filename": "32. Anexo III P1-2 ZA_Propuesta economica.xlsx",
                    "price_input_pending": True,
                },
            },
            {
                "id": "li-mat-a",
                "document_id": "doc-mat-a",
                "concepto_raw": "BOLSA DE PLÁSTICO CHICA 55X60",
                "concepto_norm": "bolsa de plástico chica 55x60",
                "unidad": "KILO",
                "cantidad": 1528,
                "precio_unitario": 0.0,
                "sheet_name": "PARTIDA 2 ZONA A",
                "row_index": 3,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "monthly_material_requirement",
                    "zone": "A",
                    "source_filename": "32. Anexo III P1-2 ZA_Propuesta economica.xlsx",
                    "price_input_pending": True,
                },
            },
        ],
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)

    out = await agent.process(
        _agent_input(
            "s-structured-slots",
            company_id="co_ps5",
            compliance_master_list={
                "tecnico": [
                    {
                        "id": "t1",
                        "descripcion": "Catálogo de conceptos con cantidades y precios unitarios",
                        "source": "bases_isapeg.pdf",
                        "page": 3,
                        "snippet": "Presentar catálogo de conceptos con cantidades y precios unitarios.",
                    },
                    {
                        "id": "t2",
                        "descripcion": "Análisis de precios unitarios",
                        "source": "bases_isapeg.pdf",
                        "page": 3,
                        "snippet": "Integrar análisis de precios unitarios por concepto.",
                    },
                ]
            },
        )
    )

    assert out.status == AgentStatus.WAITING_FOR_DATA
    miss = out.data.get("missing") or []
    assert miss and miss[0].get("type") == "economic_price"
    assert str(miss[0].get("field") or "").startswith("price_struct_")
    assert "zona a" in str(miss[0].get("label") or "").lower()
    oi = miss[0].get("original_item") or {}
    assert oi.get("row_index") == 11
    assert "propuesta economica.xlsx" in str(oi.get("source") or "").lower()
    assert "estructura de cantidades" in str(out.message or "").lower()


@pytest.mark.asyncio
async def test_tabular_prices_skip_generic_price_source_blocking():
    """Con precios en session_line_items no debe pedir fuente genérica (p. ej. Propuesta Técnica)."""
    mem = _memory_stub(
        company={"id": "co_tab", "master_profile": {"catalog": []}},
        line_items=[
            {
                "id": "li-oferta-1",
                "concepto_raw": "Suministro e instalación de paneles solares",
                "concepto_norm": "suministro e instalacion de paneles solares",
                "precio_unitario": 2586233.0,
                "cantidad": 1,
                "unidad": "Lote",
                "extra": {"price_column_index": 4, "source_filename": "ofertas.docx"},
            }
        ],
    )
    ctx = MCPContextManager(mem)
    agent = EconomicAgent(ctx)
    payload = (
        '{"items": [{"concepto": "Suministro e instalación de paneles solares", '
        '"concepto_id": "li-oferta-1", "cantidad": 1, "precio_unitario": 2586233.0, '
        '"subtotal": 2586233.0, "status": "matched"}], "alertas": []}'
    )

    with (
        patch.object(agent, "llm") as mock_llm,
        patch.object(agent, "vector_db") as mock_vec,
        patch(
            "app.agents.economic.validate_economic_proposal",
            return_value=EconomicValidationResult(perfil_usado="generic"),
        ),
    ):
        mock_llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
        mock_vec.query_texts = MagicMock(return_value={"documents": []})
        out = await agent.process(
            _agent_input(
                "s-tabular-skip-ps",
                company_id="co_tab",
                compliance_master_list={
                    "tecnico": [
                        {
                            "id": "t_prop",
                            "descripcion": "Propuesta Técnica",
                            "source": "bases.pdf",
                            "page": 12,
                            "snippet": "Entregar propuesta técnica en sobre 2.",
                        },
                    ]
                },
            )
        )

    assert out.status != AgentStatus.WAITING_FOR_DATA or (
        str((out.data.get("missing") or [{}])[0].get("input_mode") or "") != "price_source"
    )
    assert "fuente real de precios" not in str(out.message or "").lower()


def test_human_economic_blocking_summary_prioriza_ux_user_message():
    """Resumen humano: prioriza ux.user_message del primer evento con severidad block."""
    vr = EconomicValidationResult(blocking_issues=["tipo: detalle técnico largo"])
    evs = [
        {
            "severity": "block",
            "error_type": "precios_positivos",
            "ux": {"title": "Totales", "user_message": "El subtotal no coincide con la suma de partidas."},
        }
    ]
    s = _human_economic_blocking_summary(evs, vr)
    assert "subtotal" in s.lower()
    assert "totales" in s.lower()


def test_human_economic_blocking_summary_sin_ux_usa_primer_blocking_issue():
    """Sin eventos UX, el resumen humano toma el primer blocking_issue (texto plano)."""
    vr = EconomicValidationResult(blocking_issues=["Falta IVA en la fila de totales."])
    s = _human_economic_blocking_summary([], vr)
    assert "iva" in s.lower()
    assert "totales" in s.lower()


def test_human_economic_blocking_summary_acepta_validation_result_dict():
    """Persistencia en sesión usa dict (JSON); el resumen debe leer blocking_issues igual."""
    vr_dict = {"blocking_issues": ["totales: la suma no coincide con el subtotal."]}
    s = _human_economic_blocking_summary([], vr_dict)
    assert "subtotal" in s.lower() or "suma" in s.lower()
