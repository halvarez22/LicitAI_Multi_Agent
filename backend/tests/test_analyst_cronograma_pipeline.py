"""
Prueba acotada: el Analista arma contexto con calendario/cronograma y persiste
las seis claves canónicas del cronograma (texto de bases 100 % sintético).
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput
from app.services.analyst_output_normalize import normalize_reglas_economicas_dict


# Bases ficticias: fechas y eventos genéricos (no expediente real).
_CALENDARIO_SINTETICO = """
3.1. Plazos del procedimiento (ejemplo genérico).
Publicación de la convocatoria: 05 de febrero de 2031 en el portal electrónico de contratación.
Visita a las instalaciones: 12 de febrero de 2031 a las 10:00 horas, en las oficinas del área requirente.
Junta de aclaraciones a las bases: 14 de febrero de 2031 a las 11:00 horas, mismo portal.
Presentación y apertura de proposiciones: 25 de febrero de 2031 a las 09:00 horas.
Fallo: 05 de marzo de 2031 a las 12:00 horas.
Firma del contrato: 10 de marzo de 2031 a las 13:00 horas.
"""

_REQS_SINTETICO = (
    "Requisitos de participación genéricos: identificación oficial, experiencia comprobable, "
    "no inhabilitación. " * 35
)

_EVAL_SINTETICO = (
    "Criterios de evaluación: propuesta técnica y económica con ponderación según bases tipo. " * 35
)


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


async def _smart_search_side_effect(session_id, query, n_results=10, vector_db=None, expand_context=True):
    ql = (query or "").lower()
    if "criterios" in ql and "evaluacion" in ql:
        return _EVAL_SINTETICO
    if "descripción" in ql or "dotación" in ql:
        return _REQS_SINTETICO
    if "importe" in ql or "partidas" in ql or "anexo" in ql:
        return _REQS_SINTETICO
    if "exclusión" in ql or "descalificación" in ql:
        return _REQS_SINTETICO
    if "elegibilidad" in ql or ("requisitos para participar" in ql and "causas" not in ql):
        return _REQS_SINTETICO
    return _CALENDARIO_SINTETICO


@pytest.mark.asyncio
async def test_analista_inyecta_calendario_en_prompt_y_cronograma_tiene_seis_hitos():
    """Verifica recuperación de contexto de fechas + salida estructurada del cronograma."""
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    async def fake_generate(*, prompt, system_prompt=None, format=None, correlation_id=None):
        assert "SECCIÓN FECHAS" in prompt
        assert "05 de febrero de 2031" in prompt
        assert "publicacion_convocatoria" in prompt
        body = {
            "cronograma": {
                "publicacion_convocatoria": "05 de febrero de 2031 en el portal electrónico de contratación",
                "visita_instalaciones": "12 de febrero de 2031 a las 10:00 horas, oficinas del área requirente",
                "junta_aclaraciones": "14 de febrero de 2031 a las 11:00 horas, mismo portal",
                "presentacion_proposiciones": "25 de febrero de 2031 a las 09:00 horas",
                "fallo": "05 de marzo de 2031 a las 12:00 horas",
                "firma_contrato": "10 de marzo de 2031 a las 13:00 horas",
            },
            "requisitos_participacion": [],
            "requisitos_filtro": ["Identificación oficial"],
            "garantias": {"seriedad_oferta": "No especificado", "cumplimiento": "No especificado"},
            "criterios_evaluacion": "Puntos y Porcentajes",
            "reglas_economicas": normalize_reglas_economicas_dict({}),
            "alcance_operativo": [],
        }
        return SimpleNamespace(success=True, response=json.dumps(body, ensure_ascii=False), error=None)

    agent.llm.generate = AsyncMock(side_effect=fake_generate)

    import app.agents.analyst as analyst_module

    with (
        patch.object(agent, "smart_search", new=AsyncMock(side_effect=_smart_search_side_effect)),
        patch.multiple(
            analyst_module.settings,
            EXPERIENCE_LAYER_ENABLED=False,
            CONFIDENCE_ENABLED=False,
            CONFIDENCE_SHADOW_MODE=False,
        ),
    ):
        inp = AgentInput(session_id="sess-cronograma-sintetico", mode="analysis_only")
        out = await agent.process(inp)

    assert hasattr(out, "status")
    assert str(out.status.value) == "success"
    cg = out.data["cronograma"]
    assert set(cg.keys()) == {
        "publicacion_convocatoria",
        "visita_instalaciones",
        "junta_aclaraciones",
        "presentacion_proposiciones",
        "fallo",
        "firma_contrato",
    }
    assert "2031" in cg["publicacion_convocatoria"]
    assert "2031" in cg["firma_contrato"]
    assert cg["junta_aclaraciones"] != "No especificado"
    agent.llm.generate.assert_awaited_once()
