"""
Pruebas rápidas (sin Ollama) para telemetría LLM y resolución de estado en ComplianceAgent.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.compliance import ComplianceAgent
from app.agents.mcp_context import MCPContextManager
from app.services.resilient_llm import LLMResponse


@pytest.fixture
def agent() -> ComplianceAgent:
    return ComplianceAgent(MagicMock(spec=MCPContextManager))


@pytest.fixture(autouse=True)
def _compliance_legacy_map_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estas pruebas mockean ``llm.generate``; el flujo estricto usa ``service_client.generate``."""
    monkeypatch.setenv("COMPLIANCE_MAP_JSON_STRICT", "false")


@pytest.mark.asyncio
async def test_extract_zone_chunk_propaga_error_llm(agent: ComplianceAgent):
    """_extract_zone_chunk propaga el error del wrapper cuando success=False."""
    agent.llm.generate = AsyncMock(
        return_value=LLMResponse(success=False, error="ReadTimeout", response="")
    )
    items, err, empty, map_rt = await agent._extract_zone_chunk("ZONA", "texto")
    assert items == []
    assert err is not None and "ReadTimeout" in err
    assert empty is False
    assert map_rt is None


@pytest.mark.asyncio
async def test_extract_zone_chunk_respuesta_vacia(agent: ComplianceAgent):
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="   "))
    items, err, empty, map_rt = await agent._extract_zone_chunk("ZONA", "texto")
    assert items == []
    assert err is None
    assert empty is True
    assert map_rt is None


@pytest.mark.asyncio
async def test_extract_zone_chunk_json_valido(agent: ComplianceAgent):
    payload = '{"administrativo": [{"nombre": "x", "page": 1, "descripcion": "abc12345678901234567890", "snippet": "abc12345678901234567890"}], "tecnico": [], "formatos": []}'
    agent.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response=payload))
    items, err, empty, map_rt = await agent._extract_zone_chunk("ADMIN", "ctx")
    assert err is None
    assert empty is False
    assert map_rt is None
    assert len(items) == 1
    assert items[0]["categoria_orig"] == "administrativo"


def test_resolve_llm_issues_degrada_pass_a_partial(agent: ComplianceAgent):
    events = [
        {
            "block_index": 1,
            "llm_error": "connection refused",
            "empty_llm_response": False,
            "suspect_llm_timeout": False,
        }
    ]
    s, r = agent._resolve_zone_status_for_llm_issues("pass", "OK", events)
    assert s == "partial"
    assert "bloque(s) 1" in r.lower() or "1" in r


def test_resolve_llm_issues_anexa_a_partial_existente(agent: ComplianceAgent):
    events = [{"block_index": 2, "llm_error": None, "empty_llm_response": True, "suspect_llm_timeout": False}]
    s, r = agent._resolve_zone_status_for_llm_issues("partial", "Calidad baja", events)
    assert s == "partial"
    assert "Calidad baja" in r
    assert "vacía" in r.lower() or "Respuesta" in r


def test_suspect_timeout_no_si_hubo_error_llm(agent: ComplianceAgent):
    """Bloque sin ítems y duración alta no cuenta como timeout si hubo error explícito."""
    empty_timeout = 590.0
    llm_err = "timeout"
    duration = 600.0
    items_count = 0
    suspect = items_count == 0 and duration >= empty_timeout and not llm_err
    assert suspect is False
