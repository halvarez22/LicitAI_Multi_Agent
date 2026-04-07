"""
Flujo analista: reglas económicas, alcance operativo y datos_tabulares (memoria mockeada).
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.analyst import AnalystAgent
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput

_CAL = "Calendario genérico. " * 40
_PART = "Participación genérica. " * 40
_FILT = "Exclusión genérica. " * 40
_ECON = "Importe mínimo seis meses importe máximo once meses anexo 1 partidas. " * 20
_ALC = "ÁREA ASIGNADA TURNO 24 HORAS elementos 4 LUN-DOM. " * 25
_EVAL = "Evaluación puntos y porcentajes. " * 40


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


async def _ss_six(session_id, query, n_results=10, vector_db=None, expand_context=True):
    ql = (query or "").lower()
    if "evaluacion" in ql and "criterios" in ql:
        return _EVAL
    if "descripción unidad cantidad" in ql or "dotación" in ql or "turno horario" in ql:
        return _ALC
    if "importe" in ql or "partidas" in ql or "anexo" in ql:
        return _ECON
    if "exclusión" in ql or "descalificación" in ql:
        return _FILT
    if "elegibilidad" in ql or ("requisitos para participar" in ql and "causas" not in ql):
        return _PART
    return _CAL


@pytest.mark.asyncio
async def test_analista_reglas_alcance_y_datos_tabulares():
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    reglas = {
        "referencia_partidas_anexos_citados": "Anexo 1",
        "criterio_importe_minimo_o_plazo_inferior": "6 meses",
        "criterio_importe_maximo_o_plazo_superior": "11 meses",
        "meses_o_periodo_minimo_citado": "6",
        "meses_o_periodo_maximo_citado": "11",
        "modalidad_contratacion_observada": "Contrato abierto",
        "vinculacion_presupuesto_partida": "Presupuesto por partida",
        "otras_reglas_oferta_precio": "No especificado",
    }
    body = {
        "cronograma": {
            "publicacion_convocatoria": "No especificado",
            "visita_instalaciones": "No especificado",
            "junta_aclaraciones": "No especificado",
            "presentacion_proposiciones": "No especificado",
            "fallo": "No especificado",
            "firma_contrato": "No especificado",
        },
        "requisitos_participacion": [],
        "requisitos_filtro": [],
        "garantias": {"seriedad_oferta": "No especificado", "cumplimiento": "No especificado"},
        "criterios_evaluacion": "Puntos y Porcentajes",
        "reglas_economicas": reglas,
        "alcance_operativo": [
            {
                "ubicacion_o_area": "Hospital",
                "puesto_funcion_o_servicio": "Vigilancia",
                "turno": "24 HORAS",
                "horario": "08:00",
                "cantidad_o_elementos": "4",
                "dias_aplicables": "LUN-DOM",
                "texto_literal_fila": "Hospital vigilancia 24h",
            }
        ],
    }

    async def fake_generate(*, prompt, **kwargs):
        assert "SECCIÓN ECONÓMICA Y PARTIDAS" in prompt
        assert "SECCIÓN ALCANCE OPERATIVO" in prompt
        assert "reglas_economicas" in prompt
        return SimpleNamespace(success=True, response=json.dumps(body, ensure_ascii=False), error=None)

    agent.llm.generate = AsyncMock(side_effect=fake_generate)

    import app.agents.analyst as analyst_module

    with (
        patch.object(agent, "smart_search", new=AsyncMock(side_effect=_ss_six)),
        patch.multiple(
            analyst_module.settings,
            EXPERIENCE_LAYER_ENABLED=False,
            CONFIDENCE_ENABLED=False,
            CONFIDENCE_SHADOW_MODE=False,
        ),
    ):
        out = await agent.process(AgentInput(session_id="sess-econ-alc", mode="analysis_only"))

    assert out.status.value == "success"
    assert out.data["reglas_economicas"]["meses_o_periodo_minimo_citado"] == "6"
    assert len(out.data["alcance_operativo"]) == 1
    assert out.data["alcance_operativo"][0]["cantidad_o_elementos"] == "4"
    dt = out.data["datos_tabulares"]
    assert "line_items_count" in dt
    assert dt["line_items_count"] == 0
    assert dt["texto_sugiere_partidas_o_anexo_tabular"] is True
    assert dt.get("alerta_faltante")
