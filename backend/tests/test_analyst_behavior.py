"""
AnalystAgent: contrato de salida, umbral de contexto y parsing JSON (LLM y vector DB mockeados).
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.agents.analyst as analyst_module
from app.agents.analyst import AnalystAgent, normalize_cronograma_dict, normalize_requisitos_participacion_list
from app.services.analyst_output_normalize import normalize_reglas_economicas_dict
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput


def _agent_input(session_id: str) -> AgentInput:
    return AgentInput(session_id=session_id, mode="analysis_only")


def _llm_ok(response_str: str) -> SimpleNamespace:
    return SimpleNamespace(success=True, response=response_str, error=None)


_SETTINGS_OFF = dict(
    EXPERIENCE_LAYER_ENABLED=False,
    CONFIDENCE_ENABLED=False,
    CONFIDENCE_SHADOW_MODE=False,
)

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


def _empty_reglas_json() -> str:
    return json.dumps(normalize_reglas_economicas_dict({}), ensure_ascii=False)

@pytest.mark.asyncio
async def test_contexto_insuficiente_no_invoca_llm():
    """Si el contexto reunido es muy corto, falla antes del LLM (indexación vacía)."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)
    
    # Mockear el LLM del agente
    agent.llm.generate = AsyncMock(return_value=_llm_ok("{}"))

    with (
        patch.multiple(analyst_module.settings, **_SETTINGS_OFF),
        patch.object(agent, "smart_search", new_callable=AsyncMock, return_value=""),
    ):
        out = await agent.process(_agent_input("sess-analyst-1"))

    agent.llm.generate.assert_not_called()
    assert out["status"] == "error"
    assert "insuficiente" in out.get("message", "").lower()
    ctx.memory.save_agent_state.assert_not_awaited()

@pytest.mark.asyncio
async def test_exito_parsea_json_persiste_y_registra_tarea():
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    bloque = "Texto de bases con junta de aclaraciones el 10/10/2025 y requisitos legales. " * 20
    payload = (
        '{"cronograma": {"junta_aclaraciones": "10/10", "presentacion_proposiciones": "15/10", '
        '"fallo": "20/10"}, "requisitos_participacion": [], "requisitos_filtro": ["Presentar RFC"], '
        '"garantias": {"seriedad_oferta": "5%", "cumplimiento": "10%"}, '
        '"criterios_evaluacion": "Puntos y Porcentajes", '
        '"reglas_economicas": ' + _empty_reglas_json() + ', "alcance_operativo": []}'
    )

    agent.llm.generate = AsyncMock(return_value=_llm_ok(payload))
    mock_search = AsyncMock(return_value=bloque)
    
    with (
        patch.multiple(analyst_module.settings, **_SETTINGS_OFF),
        patch.object(agent, "smart_search", new=mock_search),
    ):
        out = await agent.process(_agent_input("sess-analyst-2"))

    assert out.status.value == "success"
    assert out.agent_id == "analyst_001"
    assert out.data["criterios_evaluacion"] == "Puntos y Porcentajes"
    assert out.data["requisitos_filtro"] == ["Presentar RFC"]
    cg = out.data["cronograma"]
    assert cg["junta_aclaraciones"] == "10/10"
    assert cg["presentacion_proposiciones"] == "15/10"
    assert cg["fallo"] == "20/10"
    for k in ("publicacion_convocatoria", "visita_instalaciones", "firma_contrato"):
        assert k in cg and cg[k] == "No especificado"

    ctx.memory.save_agent_state.assert_awaited()
    call_kw = ctx.memory.save_agent_state.await_args
    assert call_kw[0][0] == "analyst_001"
    assert call_kw[0][1] == "sess-analyst-2"
    assert call_kw[0][2]["last_analysis"]["garantias"]["seriedad_oferta"] == "5%"

    ctx.memory.save_session.assert_awaited()
    saved = ctx.memory.save_session.await_args[0][1]
    tasks = saved.get("tasks_completed", [])
    assert any(t.get("task") == "analisis_bases" for t in tasks)

    agent.llm.generate.assert_awaited_once()

@pytest.mark.asyncio
async def test_respuesta_con_fence_markdown_se_parsea():
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    inner = (
        '{"cronograma": {"junta_aclaraciones": "a", "presentacion_proposiciones": "b", "fallo": "c"}, '
        '"requisitos_participacion": [], "requisitos_filtro": [], '
        '"garantias": {"seriedad_oferta": "n/a", "cumplimiento": "n/a"}, "criterios_evaluacion": "Costo Menor", '
        '"reglas_economicas": ' + _empty_reglas_json() + ', "alcance_operativo": []}'
    )
    fenced = "```json\n" + inner + "\n```"

    agent.llm.generate = AsyncMock(return_value=_llm_ok(fenced))

    with (
        patch.multiple(analyst_module.settings, **_SETTINGS_OFF),
        patch.object(agent, "smart_search", new_callable=AsyncMock, return_value="x" * 300),
    ):
        out = await agent.process(_agent_input("sess-analyst-3"))

    assert out.status.value == "success"
    assert out.data["criterios_evaluacion"] == "Costo Menor"

@pytest.mark.asyncio
async def test_json_ilegible_devuelve_partial_con_marca_error():
    """Industrialización: El agente ahora marca el estado como 'partial' si el JSON es basura."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    # Parcheamos la instancia ya creada en el constructor
    agent.llm.generate = AsyncMock(return_value=_llm_ok("NO ES JSON {{{"))

    with (
        patch.multiple(analyst_module.settings, **_SETTINGS_OFF),
        patch.object(agent, "smart_search", new_callable=AsyncMock, return_value="y" * 300),
    ):
        out = await agent.process(_agent_input("sess-analyst-4"))

    assert out.status.value == "partial"
    assert out.data.get("error") == "Error al parsear respuesta del LLM"
    assert "raw" in out.data
    ctx.memory.save_agent_state.assert_awaited()

@pytest.mark.asyncio
async def test_llm_generate_usa_parameters_correctly():
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    agent.llm.generate = AsyncMock(
        return_value=_llm_ok(
            '{"cronograma":{"junta_aclaraciones":"n","presentacion_proposiciones":"n","fallo":"n"},'
            '"requisitos_participacion":[],"requisitos_filtro":[],'
            '"garantias":{"seriedad_oferta":"n","cumplimiento":"n"},"criterios_evaluacion":"Binario",'
            '"reglas_economicas":' + _empty_reglas_json() + ',"alcance_operativo":[]}'
        )
    )

    with (
        patch.multiple(analyst_module.settings, **_SETTINGS_OFF),
        patch.object(agent, "smart_search", new_callable=AsyncMock, return_value="z" * 300),
    ):
        await agent.process(_agent_input("sess-analyst-5"))

    kwargs = agent.llm.generate.await_args.kwargs
    assert kwargs.get("format") == "json"
    assert "ANALISTA FORENSE" in agent.llm.generate.await_args.kwargs.get("system_prompt", "").upper()


@pytest.mark.asyncio
async def test_json_incompleto_devuelve_partial():
    """Industrialización: Si el JSON es válido pero faltan claves obligatorias, debe ser partial."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    # JSON válido pero le falta 'garantias' y 'criterios_evaluacion'
    incomplete_json = '{"cronograma": {}, "requisitos_filtro": []}'
    agent.llm.generate = AsyncMock(return_value=_llm_ok(incomplete_json))

    with (
        patch.multiple(analyst_module.settings, **_SETTINGS_OFF),
        patch.object(agent, "smart_search", new_callable=AsyncMock, return_value="z" * 300),
    ):
        out = await agent.process(_agent_input("sess-analyst-6"))

    assert out.status.value == "partial"
    # El resultado se guarda igualmente
    assert "cronograma" in out.data


def test_normalize_requisitos_participacion_list_mezcla_dicts_y_strings():
    raw = [
        {"inciso": "a", "texto_literal": "Obligación uno"},
        {"snippet": "Obligación dos"},
        "Obligación tres",
    ]
    out = normalize_requisitos_participacion_list(raw)
    assert len(out) == 3
    assert out[0]["inciso"] == "a"
    assert "Obligación dos" in out[1]["texto_literal"]


def test_normalize_cronograma_dict_alias_y_vacios():
    raw = {"Publicación": "01/01/2030 en portal", "visita": "02/01/2030", "firma del contrato": "03/01/2030"}
    out = normalize_cronograma_dict(raw)
    assert out["publicacion_convocatoria"] == "01/01/2030 en portal"
    assert out["visita_instalaciones"] == "02/01/2030"
    assert out["firma_contrato"] == "03/01/2030"
    assert out["junta_aclaraciones"] == "No especificado"
