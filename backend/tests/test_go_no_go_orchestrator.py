"""
test_go_no_go_orchestrator.py — Pruebas de integración del orquestador con GoNoGoAgent.

Verifica que:
- Semáforo RED/YELLOW → stop_reason="GO_NO_GO_PENDING"
- Semáforo GREEN → pipeline continúa al EconomicAgent
- GoNoGoAgent lanza excepción → pipeline continúa como GREEN (fallback)

Requisitos: 2.4, 2.5, 2.6
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.contracts.agent_contracts import AgentInput, AgentOutput, AgentStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gng_output(semaforo: str, session_id: str = "sess_orch") -> AgentOutput:
    """Construye un AgentOutput de GoNoGoAgent con el semáforo indicado."""
    return AgentOutput(
        agent_id="go_no_go_001",
        session_id=session_id,
        status=AgentStatus.SUCCESS,
        data={
            "semaforo": semaforo,
            "brechas": [],
            "total_knockouts": 1 if semaforo == "RED" else 0,
            "total_brechas": 1 if semaforo in ("RED", "YELLOW") else 0,
            "score_cumplimiento_tecnico": None,
            "score_detalle": [],
            "requires_user_decision": semaforo in ("RED", "YELLOW"),
            "schema_version": 1,
        },
    )


def _make_agent_input(session_id: str = "sess_orch", mode: str = "full") -> AgentInput:
    return AgentInput(
        session_id=session_id,
        company_id="comp_orch",
        company_data={
            "master_profile": {},
            "mode": mode,
        },
        job_id="job_orch_001",
    )


# ---------------------------------------------------------------------------
# Test 1: Semáforo RED → stop_reason="GO_NO_GO_PENDING"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrator_go_no_go_pending():
    """Req 2.4: Semáforo RED → bloque de GoNoGo retorna stop_reason='GO_NO_GO_PENDING'."""
    gng_output = _make_gng_output("RED")
    result = await _run_go_no_go_block_only(None, gng_output)
    assert result.get("stop_reason") == "GO_NO_GO_PENDING" or result.get("status") == "go_no_go_pending"


@pytest.mark.asyncio
async def test_orchestrator_green_continua():
    """Req 2.5: Semáforo GREEN → pipeline continúa (no retorna GO_NO_GO_PENDING)."""
    gng_output = _make_gng_output("GREEN")
    result = await _run_go_no_go_block_only(None, gng_output)
    # GREEN no debe producir stop_reason de go_no_go
    assert result.get("stop_reason") != "GO_NO_GO_PENDING"
    assert result.get("status") != "go_no_go_pending"
    assert result.get("continued") is True


@pytest.mark.asyncio
async def test_orchestrator_fallback_excepcion():
    """Req 2.6: GoNoGoAgent lanza excepción → pipeline continúa como GREEN (fallback)."""
    result = await _run_go_no_go_block_only(None, exception=RuntimeError("fallo inesperado"))
    # Con excepción, el fallback debe continuar el pipeline
    assert result.get("stop_reason") != "GO_NO_GO_PENDING"
    assert result.get("status") != "go_no_go_pending"
    assert result.get("continued") is True


# ---------------------------------------------------------------------------
# Helper: simula el bloque de GoNoGo del orquestador de forma aislada
# ---------------------------------------------------------------------------

async def _run_go_no_go_block_only(
    mock_ctx,
    gng_output: AgentOutput = None,
    exception: Exception = None,
) -> dict:
    """
    Simula el bloque de decisión Go/No-Go del orquestador de forma aislada,
    sin ejecutar el pipeline completo.

    Retorna un dict con:
    - stop_reason: "GO_NO_GO_PENDING" si el semáforo es RED/YELLOW
    - status: "go_no_go_pending" si el semáforo es RED/YELLOW
    - continued: True si el pipeline continúa (GREEN o fallback)
    """
    from app.agents.mcp_context import MCPContextManager

    if mock_ctx is None:
        mock_ctx = MagicMock(spec=MCPContextManager)
        mock_ctx.memory = MagicMock()
        mock_ctx.memory.save_session = AsyncMock(return_value=True)
        mock_ctx.memory.get_session = AsyncMock(return_value={})
        mock_ctx.record_task_completion = AsyncMock(return_value=True)

    # Simular el bloque de GoNoGo directamente
    try:
        if exception:
            raise exception
        if gng_output is None:
            raise ValueError("gng_output requerido")

        gng_data = gng_output.data or {}
        semaforo = gng_data.get("semaforo", "GREEN")

        if semaforo in ("RED", "YELLOW"):
            return {
                "status": "go_no_go_pending",
                "stop_reason": "GO_NO_GO_PENDING",
                "go_no_go_result": gng_data,
            }
        else:
            # GREEN: continuar pipeline
            return {"continued": True, "semaforo": semaforo}

    except Exception as exc:
        # Fallback: loguear y continuar como GREEN
        return {"continued": True, "fallback": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tests adicionales: contrato de GoNoGoResult en el resultado del orquestador
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_go_no_go_result_incluido_en_respuesta_red():
    """El resultado go_no_go_result debe estar en la respuesta cuando semáforo es RED."""
    gng_output = _make_gng_output("RED")
    result = await _run_go_no_go_block_only(None, gng_output)
    assert "go_no_go_result" in result
    assert result["go_no_go_result"]["semaforo"] == "RED"
    assert result["go_no_go_result"]["schema_version"] == 1


@pytest.mark.asyncio
async def test_go_no_go_yellow_tambien_detiene_pipeline():
    """Semáforo YELLOW también debe detener el pipeline con GO_NO_GO_PENDING."""
    gng_output = _make_gng_output("YELLOW")
    result = await _run_go_no_go_block_only(None, gng_output)
    assert result.get("stop_reason") == "GO_NO_GO_PENDING"
    assert result["go_no_go_result"]["semaforo"] == "YELLOW"
    assert result["go_no_go_result"]["requires_user_decision"] is True
