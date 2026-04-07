"""
Pruebas del OrchestratorAgent con dependencias mockeadas (sin LLM ni DB real).
Documentan el contrato de respuesta y regresiones obvias del flujo.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent


def _memory_stub(session: dict | None = None):
    mem = AsyncMock()
    sess = session if session is not None else {"tasks_completed": []}
    mem.get_session = AsyncMock(return_value=sess)
    mem.save_session = AsyncMock(return_value=True)
    mem.get_documents = AsyncMock(return_value=[])
    mem.get_line_items_for_session = AsyncMock(return_value=[])
    mem.replace_line_items_for_document = AsyncMock(return_value=True)
    mem.disconnect = AsyncMock()
    return mem


@pytest.mark.asyncio
async def test_orchestrator_analysis_only_ejecuta_tres_agentes_y_exito():
    ctx = MCPContextManager(_memory_stub())
    orch = OrchestratorAgent(ctx)

    async def analyst_ok(*a, **k):
        return {"status": "success", "data": {}}

    async def compliance_ok(*a, **k):
        return {"status": "success", "data": {"tecnico": [{"id": "t1", "texto": "x"}]}}

    async def economic_ok(*a, **k):
        return {
            "status": "success",
            "data": {"items": [], "grand_total": 0},
        }

    with patch("app.agents.analyst.AnalystAgent") as Ma, patch(
        "app.agents.compliance.ComplianceAgent"
    ) as Mc, patch("app.agents.economic.EconomicAgent") as Me:
        Ma.return_value.process = AsyncMock(side_effect=analyst_ok)
        Mc.return_value.process = AsyncMock(side_effect=compliance_ok)
        Me.return_value.process = AsyncMock(side_effect=economic_ok)

        out = await orch.process(
            "sess-1",
            {
                "company_id": "co_1",
                "company_data": {"mode": "analysis_only"},
            },
        )

    assert out["status"] == "success"
    assert "analysis" in out["results"]
    assert "compliance" in out["results"]
    assert "economic" in out["results"]
    steps = out["orchestrator_decision"]["next_steps"]
    assert "analysis_it_0" in steps
    assert "compliance_it_0" in steps
    assert "economic_analysis_OK" in steps


@pytest.mark.asyncio
async def test_orchestrator_detiene_por_economic_gap_incluye_results_parciales():
    ctx = MCPContextManager(_memory_stub())
    orch = OrchestratorAgent(ctx)

    with patch("app.agents.analyst.AnalystAgent") as Ma, patch(
        "app.agents.compliance.ComplianceAgent"
    ) as Mc, patch("app.agents.economic.EconomicAgent") as Me:
        Ma.return_value.process = AsyncMock(return_value={"status": "ok"})
        Mc.return_value.process = AsyncMock(
            return_value={"status": "success", "data": {"tecnico": [{"x": 1}]}}
        )
        Me.return_value.process = AsyncMock(
            return_value={
                "status": "waiting_for_data",
                "message": "Faltan precios",
                "data": {
                    "missing": [{"field": "price_x"}],
                    "alertas_contexto_bases": [
                        "[Partidas/sesión] Cargar hoja de partidas.",
                    ],
                    "contexto_bases_analista": {
                        "reglas_economicas": {},
                        "alcance_operativo_filas": 0,
                        "datos_tabulares": {},
                    },
                },
            }
        )

        out = await orch.process(
            "sess-gap",
            {"company_id": "co_1", "company_data": {"mode": "analysis_only"}},
        )

    assert out["status"] == "waiting_for_data"
    assert out["chatbot_message"] == "Faltan precios"
    assert out["orchestrator_decision"]["stop_reason"] == "ECONOMIC_GAP"
    wh = out["orchestrator_decision"].get("waiting_hints") or {}
    assert wh.get("missing_price_count") == 1
    assert any("Partidas" in str(x) for x in (wh.get("alertas_contexto_bases") or []))
    assert "results" in out
    assert "analysis" in out["results"] and "compliance" in out["results"]
    assert out["results"]["economic"]["status"] == "waiting_for_data"


@pytest.mark.asyncio
async def test_orchestrator_modo_desconocido_no_ejecuta_fases():
    ctx = MCPContextManager(_memory_stub())
    orch = OrchestratorAgent(ctx)

    with patch("app.agents.analyst.AnalystAgent") as Ma:
        out = await orch.process(
            "sess-x",
            {"company_data": {"mode": "solo_lectura_inventado"}},
        )
        Ma.assert_not_called()

    assert out["status"] == "error"
    assert out["orchestrator_decision"]["stop_reason"] == "INVALID_MODE"
    assert "Modo" in (out.get("message") or "")


@pytest.mark.asyncio
async def test_orchestrator_compliance_excepcion_no_invoca_economic_politica_b():
    """Política B: excepción en Compliance → error registrado, sin Economic."""
    ctx = MCPContextManager(_memory_stub())
    orch = OrchestratorAgent(ctx)

    async def boom(*a, **k):
        raise RuntimeError("compliance down")

    with patch("app.agents.analyst.AnalystAgent") as Ma, patch(
        "app.agents.compliance.ComplianceAgent"
    ) as Mc, patch("app.agents.economic.EconomicAgent") as Me:
        Ma.return_value.process = AsyncMock(return_value={"ok": True})
        Mc.return_value.process = AsyncMock(side_effect=boom)
        Me.return_value.process = AsyncMock(
            return_value={"status": "complete", "message": "sin técnico"}
        )

        out = await orch.process(
            "sess-fail",
            {"company_id": None, "company_data": {"mode": "analysis_only"}},
        )

    assert out["orchestrator_decision"]["stop_reason"] == "COMPLIANCE_ERROR"
    assert out["orchestrator_decision"]["aggregate_health"] == "failed"
    assert out["results"]["compliance"]["status"] == "error"
    assert "economic" not in out["results"]
    Mc.return_value.process.assert_awaited_once()
    Me.return_value.process.assert_not_awaited()


@pytest.mark.asyncio
async def test_orchestrator_compliance_partial_aun_invoca_economic():
    """Política B revisada: compliance partial o fail NO detiene, invoca a Economic."""
    ctx = MCPContextManager(_memory_stub())
    orch = OrchestratorAgent(ctx)

    with patch("app.agents.analyst.AnalystAgent") as Ma, patch(
        "app.agents.compliance.ComplianceAgent"
    ) as Mc, patch("app.agents.economic.EconomicAgent") as Me:
        Ma.return_value.process = AsyncMock(return_value={"status": "success"})
        Mc.return_value.process = AsyncMock(
            return_value={"status": "partial", "data": {"administrativo": [{"x": 1}]}}
        )
        Me.return_value.process = AsyncMock(
            return_value={"status": "complete", "message": "econ_ok"}
        )

        out = await orch.process(
            "sess-partial",
            {"company_id": None, "company_data": {"mode": "analysis_only"}},
        )

    # El decision final del orquestador refleja el estado degradado
    assert out["orchestrator_decision"]["aggregate_health"] == "partial"
    assert "economic" in out["results"]
    assert out["results"]["economic"]["status"] == "complete"
    
    # Se debe invocar al económico a pesar del partial en compliance
    Mc.return_value.process.assert_awaited_once()
    Me.return_value.process.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_compliance_fail_aun_invoca_economic():
    """Política B revisada: compliance fail NO detiene, invoca a Economic."""
    ctx = MCPContextManager(_memory_stub())
    orch = OrchestratorAgent(ctx)

    with patch("app.agents.analyst.AnalystAgent") as Ma, patch(
        "app.agents.compliance.ComplianceAgent"
    ) as Mc, patch("app.agents.economic.EconomicAgent") as Me:
        Ma.return_value.process = AsyncMock(return_value={"status": "success"})
        Mc.return_value.process = AsyncMock(
            return_value={"status": "fail", "data": {"administrativo": []}}
        )
        Me.return_value.process = AsyncMock(
            return_value={"status": "complete", "message": "econ_ok"}
        )

        out = await orch.process(
            "sess-fail-continue",
            {"company_id": None, "company_data": {"mode": "analysis_only"}},
        )

    # El decision final del orquestador refleja el estado degradado (failed)
    assert out["orchestrator_decision"]["aggregate_health"] == "failed"
    assert "economic" in out["results"]
    assert out["results"]["economic"]["status"] == "complete"
    
    # Se debe invocar al económico a pesar del fail en compliance
    Mc.return_value.process.assert_awaited_once()
    Me.return_value.process.assert_awaited_once()


