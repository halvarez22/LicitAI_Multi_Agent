import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import app.agents.analyst as analyst_module
from app.agents.analyst import AnalystAgent, build_sector_classification
from app.agents.mcp_context import MCPContextManager
from app.contracts.agent_contracts import AgentInput
from app.services.analyst_output_normalize import normalize_reglas_economicas_dict

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "vertical_mexico"
_CASES = sorted(_FIXTURE_DIR.glob("*.json"))


def _load_case(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _agent_input(session_id: str) -> AgentInput:
    return AgentInput(session_id=session_id, mode="analysis_only")


def _llm_ok(response_str: str) -> SimpleNamespace:
    return SimpleNamespace(success=True, response=response_str, error=None)


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


@pytest.mark.parametrize("fixture_path", _CASES, ids=[p.stem for p in _CASES])
def test_vertical_suite_clasificacion_pura(fixture_path: Path):
    case = _load_case(fixture_path)
    expected = case["expected"]
    out = build_sector_classification(case["context_text"], llm_data={})

    assert out["sector_id"] in expected["allowed_sector_ids"]
    assert isinstance(out.get("confidence"), float)
    assert len(out.get("evidence", [])) >= int(expected.get("min_evidence_items", 1))
    found_codes = {e.get("signal_code") for e in out.get("evidence", [])}
    for required in expected.get("required_signal_codes", []):
        assert required in found_codes


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture_path", _CASES, ids=[f"smoke::{p.stem}" for p in _CASES])
async def test_vertical_suite_smoke_analyst_contract(fixture_path: Path):
    case = _load_case(fixture_path)
    context = case["context_text"]
    ctx = MCPContextManager(_memory_stub())
    agent = AnalystAgent(ctx)

    payload = (
        '{"cronograma": {"junta_aclaraciones": "No especificado", "presentacion_proposiciones": "No especificado", '
        '"fallo": "No especificado"}, "requisitos_participacion": [], "requisitos_filtro": [], '
        '"garantias": {"seriedad_oferta": "No especificado", "cumplimiento": "No especificado"}, '
        '"criterios_evaluacion": "No especificado", '
        '"reglas_economicas": ' + _empty_reglas_json() + ', "alcance_operativo": []}'
    )
    agent.llm.generate = AsyncMock(return_value=_llm_ok(payload))

    settings_off = dict(
        EXPERIENCE_LAYER_ENABLED=False,
        CONFIDENCE_ENABLED=False,
        CONFIDENCE_SHADOW_MODE=False,
        ENHANCED_EXTRACTION_ENABLED=False,
    )

    with (
        patch.multiple(analyst_module.settings, **settings_off),
        patch.object(agent, "smart_search", new_callable=AsyncMock, return_value=context),
    ):
        out = await agent.process(_agent_input(f"suite-{case['case_id']}"))

    assert out.status.value == "success"
    for key in ("cronograma", "requisitos_participacion", "reglas_economicas", "alcance_operativo"):
        assert key in out.data
    assert "sector_classification" in out.data
    assert out.data["sector_classification"]["sector_id"] in case["expected"]["allowed_sector_ids"]
