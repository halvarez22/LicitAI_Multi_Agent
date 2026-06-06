#!/usr/bin/env python3
"""
Reanuda generation_only tras cerrar puerta económica (FSR + partidas tabulares).

Uso:
  PYTHONPATH=/app python scripts/resume_session_generation.py vigilancia_issste
"""
from __future__ import annotations

import asyncio
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _norm_concept(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def bootstrap_fsr_params_from_line_items(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Infiere parámetros FSR desde filas ``raw_calculation`` (universal, sin mapa por licitación).
    """
    by_label: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = _norm_concept(row.get("concepto_raw") or row.get("concepto_norm"))
        if key:
            by_label[key] = row

    salario_diario: Optional[float] = None
    salario_mensual: Optional[float] = None
    for key, row in by_label.items():
        price = float(row.get("precio_unitario") or 0.0)
        if price <= 0:
            continue
        if key.startswith("salario:") or key == "salario":
            salario_diario = price
        elif "salario mensual" in key or "salario mensual" == key:
            salario_mensual = price

    imss_keys = ("enfermedad", "invalidez", "cesant", "riesgos", "guarder")
    imss_sum = 0.0
    for key, row in by_label.items():
        if any(token in key for token in imss_keys):
            imss_sum += float(row.get("precio_unitario") or 0.0)

    out: Dict[str, Any] = {
        "sar": 0.02,
        "infonavit": 0.05,
        "prima_vacacional": 0.25,
        "dias_laborados": 297,
        "dias_no_laborados": 68,
    }
    if salario_mensual and salario_mensual > 0 and imss_sum > 0:
        out["imss"] = round(imss_sum / salario_mensual, 4)
    else:
        out["imss"] = 0.245

    aguinaldo_row = next(
        (row for k, row in by_label.items() if "aguinaldo" in k and "prima" not in k),
        None,
    )
    if aguinaldo_row and salario_diario and salario_diario > 0:
        ag_amount = float(aguinaldo_row.get("precio_unitario") or 0.0)
        if ag_amount > 0:
            inferred_days = round((ag_amount / salario_diario) * (365.0 / 12.0), 1)
            if 5.0 <= inferred_days <= 30.0:
                out["aguinaldo_dias"] = inferred_days
    if "aguinaldo_dias" not in out:
        out["aguinaldo_dias"] = 15

    integrado = next(
        (row for k, row in by_label.items() if "salario integrado" in k),
        None,
    )
    if integrado:
        total = float(integrado.get("precio_unitario") or 0.0)
        if total > 0:
            out["chat_override_subtotal_propuesta"] = total

    return out


def _unblock_generation_jobs(gen_state: Optional[Dict[str, Any]]) -> None:
    if not isinstance(gen_state, dict):
        return
    for job in gen_state.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        if job.get("id") in ("formats", "economic_writer", "packager", "delivery"):
            if str(job.get("status") or "").lower() in ("blocked", "error"):
                job["status"] = "pending"
    gen_state["status"] = "running"


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "vigilancia_issste"
    from app.agents.mcp_context import MCPContextManager
    from app.agents.orchestrator import OrchestratorAgent
    from app.api.deps import get_connected_memory
    from app.contracts.agent_contracts import AgentInput
    from app.agents.economic import EconomicAgent
    from app.services.economic_tabular_ingest_sync import sync_economic_pending_after_tabular_ingest

    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    company_id = str(state.get("company_id") or "").strip()
    if not company_id:
        print("ERROR: sesión sin company_id")
        sys.exit(1)

    rows = await mem.get_line_items_for_session(session_id) or []
    fsr_inputs = bootstrap_fsr_params_from_line_items(rows)
    merged_inputs = dict(state.get("economic_user_inputs") or {})
    merged_inputs.update(fsr_inputs)
    await mem.save_session(session_id, {"economic_user_inputs": merged_inputs})
    print("FSR bootstrap:", fsr_inputs)

    await sync_economic_pending_after_tabular_ingest(mem, session_id)

    ctx = MCPContextManager(mem)
    econ = EconomicAgent(ctx)
    econ_result = await econ.process(
        AgentInput(
            session_id=session_id,
            company_id=company_id,
            company_data={"mode": "generation_only"},
            correlation_id=f"resume_gen_{uuid.uuid4().hex[:8]}",
            job_id=str(uuid.uuid4()),
            mode="generation_only",
        )
    )
    print("economic_agent status:", getattr(econ_result, "status", None))
    print("economic_agent message:", str(getattr(econ_result, "message", "") or "")[:200])

    state = await mem.get_session(session_id) or {}
    gen_state = state.get("generation_state")
    _unblock_generation_jobs(gen_state)
    if isinstance(gen_state, dict):
        for job in gen_state.get("jobs") or []:
            if isinstance(job, dict) and job.get("id") == "technical":
                job["status"] = "done"
    await mem.save_session(
        session_id,
        {
            "generation_state": gen_state,
            "pending_questions": [],
            "current_question_index": 0,
        },
    )

    orch = OrchestratorAgent(ctx)
    print(f"=== generation_only resume | {session_id} ===")
    result = await orch.process(
        session_id,
        {
            "company_id": company_id,
            "mode": "generation_only",
            "resume_generation": True,
            "company_data": {"mode": "generation_only"},
            "correlation_id": f"resume_gen_{uuid.uuid4().hex[:8]}",
        },
    )
    stop = (result.get("orchestrator_decision") or {}).get("stop_reason")
    print("status:", result.get("status"))
    print("stop_reason:", stop)
    print("message:", str(result.get("message") or result.get("chatbot_message") or "")[:300])
    await mem.disconnect()
    sys.exit(0 if stop == "FINAL_OK" else 2)


if __name__ == "__main__":
    asyncio.run(main())
