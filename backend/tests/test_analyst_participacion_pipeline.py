"""
Prueba del Analista: sección de participación / elegibilidad en contexto y salida requisitos_participacion.
Texto 100 % sintético (sin expediente real).
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput
from app.services.analyst_output_normalize import normalize_reglas_economicas_dict

_CAL = "Plazos genéricos: fallo el 01/01/2032. " * 30
_PART = """
4. Requisitos para participar (texto ficticio de bases tipo).
a) Presentar declaración de integridad según el reglamento aplicable.
b) Acreditar personalidad jurídica de conformidad con el anexo de bases.
c) Contar con certificado digital vigente para CompraNet.
"""
_FILTROS = "Causas de exclusión: incumplir plazos de entrega documentada. " * 25
_EVAL = "Evaluación técnica y económica con criterios publicados en bases. " * 25


def _memory_stub():
    mem = AsyncMock()
    mem.get_session = AsyncMock(return_value={"schema_version": 1, "tasks_completed": []})
    mem.save_session = AsyncMock(return_value=True)
    mem.save_agent_state = AsyncMock(return_value=True)
    mem.get_agent_state = AsyncMock(return_value=None)
    mem.get_documents = AsyncMock(return_value=[])
    mem.get_line_items_for_session = AsyncMock(return_value=[])
    mem.disconnect = AsyncMock()
    return mem


async def _smart_search_part(session_id, query, n_results=10, vector_db=None, expand_context=True):
    ql = (query or "").lower()
    if "criterios" in ql and "evaluacion" in ql:
        return _EVAL
    if "descripción" in ql or "dotación" in ql:
        return _PART
    if "importe" in ql or "partidas" in ql or "anexo" in ql:
        return _FILTROS
    if "exclusión" in ql or "descalificación" in ql:
        return _FILTROS
    if "elegibilidad" in ql or ("requisitos para participar" in ql and "causas" not in ql):
        return _PART * 3
    return _CAL


@pytest.mark.asyncio
async def test_analista_inyecta_participacion_y_normaliza_requisitos_participacion():
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    async def fake_generate(*, prompt, system_prompt=None, format=None, correlation_id=None):
        assert "SECCIÓN PARTICIPACIÓN" in prompt
        assert "declaración de integridad" in prompt
        assert "requisitos_participacion" in prompt
        body = {
            "cronograma": {
                "publicacion_convocatoria": "No especificado",
                "visita_instalaciones": "No especificado",
                "junta_aclaraciones": "No especificado",
                "presentacion_proposiciones": "No especificado",
                "fallo": "No especificado",
                "firma_contrato": "No especificado",
            },
            "requisitos_participacion": [
                {"inciso": "a", "texto_literal": "Presentar declaración de integridad según el reglamento aplicable."},
                {"inciso": "b", "texto_literal": "Acreditar personalidad jurídica de conformidad con el anexo de bases."},
                {"inciso": "c", "texto_literal": "Contar con certificado digital vigente para CompraNet."},
            ],
            "requisitos_filtro": [],
            "garantias": {"seriedad_oferta": "No especificado", "cumplimiento": "No especificado"},
            "criterios_evaluacion": "Puntos y Porcentajes",
            "reglas_economicas": normalize_reglas_economicas_dict({}),
            "alcance_operativo": [],
        }
        return SimpleNamespace(success=True, response=json.dumps(body, ensure_ascii=False), error=None)

    agent.llm.generate = AsyncMock(side_effect=fake_generate)

    import app.agents.analyst as analyst_module

    with (
        patch.object(agent, "smart_search", new=AsyncMock(side_effect=_smart_search_part)),
        patch.multiple(
            analyst_module.settings,
            EXPERIENCE_LAYER_ENABLED=False,
            CONFIDENCE_ENABLED=False,
            CONFIDENCE_SHADOW_MODE=False,
        ),
    ):
        inp = AgentInput(session_id="sess-part-sintetico", mode="analysis_only")
        out = await agent.process(inp)

    assert str(out.status.value) == "success"
    rp = out.data["requisitos_participacion"]
    assert len(rp) == 3
    assert rp[0]["inciso"] == "a"
    assert "integridad" in rp[0]["texto_literal"].lower()
    assert out.data["requisitos_filtro"] == []
    agent.llm.generate.assert_awaited_once()
