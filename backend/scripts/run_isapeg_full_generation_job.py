#!/usr/bin/env python3
"""
Job transaccional: GENERAR PROPUESTA completa para sesión isapeg (sin UI).

Flujo: preparar sesión → orquestador generation_only (Technical→Formats→EconomicWriter
→Packager→CompraNet→Delivery→BiddingBinder) → auditoría de volumen → regresión ISSSTE.

Uso en contenedor:
  python scripts/run_isapeg_full_generation_job.py
  python scripts/run_isapeg_full_generation_job.py --session isapeg --company co_1778887651476
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DEFAULT_SESSION = "isapeg"
DEFAULT_COMPANY = "co_1778887651476"


def _build_isapeg_economic_snapshot() -> Dict[str, Any]:
    """Snapshot económico determinista (9 ítems + fórmula 275) — sin hardcode de session_id."""
    items: List[Dict[str, Any]] = [
        {
            "partida": 1,
            "concepto": "Servicio Especializado de Limpieza en Unidades Médicas - Turno Hospitalario de 24 Horas (Zona A)",
            "unidad": "Servicio Mensual",
            "cantidad": 4,
            "precio_unitario": 45250.00,
            "subtotal": 181000.00,
            "status": "matched",
        },
        {
            "partida": 1,
            "concepto": "Servicio Especializado de Limpieza en Unidades Médicas - Turno Hospitalario de 12 Horas (Zona C)",
            "unidad": "Servicio Mensual",
            "cantidad": 3,
            "precio_unitario": 45250.00,
            "subtotal": 135750.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Papel Higiénico Higiénico Jumbo (Biodegradabilidad al 90%)",
            "unidad": "Caja",
            "cantidad": 150,
            "precio_unitario": 85.00,
            "subtotal": 12750.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Toallas Interdobladas para Manos (Biodegradabilidad al 90%)",
            "unidad": "Caja",
            "cantidad": 120,
            "precio_unitario": 95.00,
            "subtotal": 11400.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Jabón Líquido Antibacteriano para Manos",
            "unidad": "Bidón 20L",
            "cantidad": 90,
            "precio_unitario": 65.00,
            "subtotal": 5850.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Cloro Concentrado al 6% de Grado Clínico",
            "unidad": "Bidón 20L",
            "cantidad": 80,
            "precio_unitario": 45.00,
            "subtotal": 3600.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Desinfectante Multiusos Hospitalario",
            "unidad": "Bidón 20L",
            "cantidad": 70,
            "precio_unitario": 110.00,
            "subtotal": 7700.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Bolsas para Basura Biodegradables (90% de biodegradabilidad)",
            "unidad": "Paquete",
            "cantidad": 200,
            "precio_unitario": 35.00,
            "subtotal": 7000.00,
            "status": "matched",
        },
        {
            "partida": 2,
            "concepto": "Suministro de Fibras y Fregadores Abrasivos para Áreas Críticas",
            "unidad": "Pieza",
            "cantidad": 100,
            "precio_unitario": 25.00,
            "subtotal": 2500.00,
            "status": "matched",
        },
    ]
    subtotal = 367550.00
    iva = 58808.00
    total = 426358.00
    tarifa = 45250.00
    dias = 15
    return {
        "status": "complete",
        "currency": "MXN",
        "total_base": subtotal,
        "grand_total": total,
        "items": items,
        "validation_result": {
            "validation_passed": True,
            "perfil_usado": "limpieza",
            "issues": [],
            "blocking_issues": [],
        },
        "billing_proportional": {
            "months": 9,
            "days_divisor": 275,
            "tarifa_mensual": tarifa,
            "dias_transcurridos": dias,
        },
        "formula_incomplete_month": {
            "dias_transcurridos": dias,
            "monto_calculado": round((tarifa * 9) / 275 * dias, 2),
            "days_divisor": 275,
            "months": 9,
        },
    }


def _mock_answer(question: Dict[str, Any]) -> str:
    if question.get("type") == "economic_price":
        return "45250"
    field = question.get("field") or ""
    if field.startswith("price_"):
        return "45250"
    if field == "rfc":
        return "RFC E2E850101XYZ"
    return f"dato mock job para {question.get('label', field)}"


async def _prepare_session(
    memory, session_id: str, company_id: str, *, resume_pipeline: bool = False
) -> Dict[str, Any]:
    from app.agents.mcp_context import MCPContextManager

    state = await memory.get_session(session_id) or {}
    if not state:
        raise RuntimeError(f"Sesión no encontrada: {session_id}")

    state["company_id"] = company_id
    if not resume_pipeline:
        state.pop("generation_state", None)

    company = await memory.get_company(company_id) or {}
    master_profile = company.get("master_profile") or {}

    snapshot = _build_isapeg_economic_snapshot()
    tasks = list(state.get("tasks_completed") or [])
    tasks = [t for t in tasks if (t.get("task") or "") not in ("economic_proposal", "stage_completed:economic")]
    tasks.append({"task": "economic_proposal", "result": snapshot})
    tasks.append(
        {
            "task": "stage_completed:economic",
            "result": {"status": "success", "data": snapshot},
        }
    )
    state["tasks_completed"] = tasks
    state["pending_questions"] = []
    state["current_question_index"] = 0

    await memory.save_session(session_id, state)
    return {"master_profile": master_profile, "snapshot": snapshot}


async def _drain_pending(memory, bot, session_id: str, company_id: str, max_turns: int = 40) -> int:
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.contracts.agent_contracts import AgentInput

    sent = 0
    for _ in range(max_turns):
        state = await memory.get_session(session_id) or {}
        pending = state.get("pending_questions") or []
        if not pending:
            break
        idx = int(state.get("current_question_index", 0))
        if idx >= len(pending):
            break
        q = pending[idx]
        inp = AgentInput(
            session_id=session_id,
            company_id=company_id,
            company_data={"query": _mock_answer(q)},
        )
        await bot.process(inp)
        sent += 1
    return sent


async def _run_orchestrator_loop(
    session_id: str, company_id: str, master_profile: Dict[str, Any], max_rounds: int = 25
) -> Dict[str, Any]:
    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.agents.mcp_context import MCPContextManager
    from app.agents.orchestrator import OrchestratorAgent
    from app.memory.factory import MemoryAdapterFactory

    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    ctx = MCPContextManager(memory)
    orch = OrchestratorAgent(ctx)
    bot = ChatbotRAGAgent(ctx)

    last: Dict[str, Any] = {}
    try:
        for rnd in range(1, max_rounds + 1):
            print(f"\n[ORCH] Ronda {rnd}/{max_rounds} generation_only…")
            last = await orch.process(
                session_id,
                {
                    "company_id": company_id,
                    "resume_generation": True,
                    "company_data": {
                        "mode": "generation_only",
                        "master_profile": master_profile,
                    },
                    "correlation_id": f"isapeg_job_{rnd}",
                    "job_id": f"job_{uuid.uuid4().hex[:12]}",
                },
            )
            status = last.get("status")
            stop = (last.get("orchestrator_decision") or {}).get("stop_reason")
            print(f"[ORCH] status={status} stop_reason={stop}")
            if status == "success":
                return last
            if status == "waiting_for_data":
                n = await _drain_pending(memory, bot, session_id, company_id)
                print(f"[ORCH] Drenado chatbot: {n} respuestas mock.")
                if n == 0:
                    print("[ORCH] Cola sin avance; abortando.")
                    break
                continue
            break
        return last
    finally:
        await memory.disconnect()


def _run_issste_regression() -> Dict[str, Any]:
    script = _ROOT / "scratch" / "run_regression_issste.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        timeout=180,
    )
    ok = proc.returncode == 0 and "8 OK de 8" in (proc.stdout or "")
    return {
        "returncode": proc.returncode,
        "ok_8_8": ok,
        "stdout_tail": (proc.stdout or "")[-2500:],
        "stderr_tail": (proc.stderr or "")[-800:],
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--company", default=DEFAULT_COMPANY)
    parser.add_argument("--skip-orch", action="store_true", help="Solo preparar + auditar")
    parser.add_argument(
        "--resume-pipeline",
        action="store_true",
        help="Conserva generation_state (reanuda tras fallo en formats/packager)",
    )
    args = parser.parse_args()

    os.environ.setdefault("LICITAI_PROP_BILLING_DAYS_DIVISOR", "275")
    os.environ.setdefault("LICITAI_PROP_BILLING_MONTHS", "9")

    from app.memory.factory import MemoryAdapterFactory

    memory = MemoryAdapterFactory.create_adapter()
    if not memory or not await memory.connect():
        print("[FATAL] Sin conexión a Postgres.")
        return 1

    report: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "session_id": args.session,
        "company_id": args.company,
        "phases": {},
    }

    try:
        prep = await _prepare_session(
            memory, args.session, args.company, resume_pipeline=args.resume_pipeline
        )
        report["phases"]["prepare"] = {"ok": True, "total_base": prep["snapshot"]["total_base"]}
        print(f"[PREP] economic_proposal inyectado (total_base={prep['snapshot']['total_base']})")
    finally:
        await memory.disconnect()

    if not args.skip_orch:
        orch_res = await _run_orchestrator_loop(
            args.session, args.company, prep["master_profile"]
        )
        report["phases"]["orchestrator"] = {
            "status": orch_res.get("status"),
            "stop_reason": (orch_res.get("orchestrator_decision") or {}).get("stop_reason"),
        }
        if orch_res.get("status") != "success":
            print("[WARN] Orquestador no terminó en success.")

    audit_path = f"/data/outputs/{args.session}/_AUDIT_FASE_A_JOB.json"
    proc_audit = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "audit_session_deliverables.py"), "--session", args.session, "--json", audit_path],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        timeout=120,
    )
    audit_data: Dict[str, Any] = {}
    if Path(audit_path).is_file():
        audit_data = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    report["phases"]["audit_deliverables"] = {
        "returncode": proc_audit.returncode,
        "phase_a_verdict": audit_data.get("phase_a_verdict"),
        "phase_a_notes": audit_data.get("phase_a_notes"),
        "inventory_summary": audit_data.get("inventory_summary"),
        "pipeline_flags": (audit_data.get("session") or {}).get("pipeline_flags"),
    }

    issste = _run_issste_regression()
    report["phases"]["issste_regression"] = issste

    phase_a_ok = audit_data.get("phase_a_verdict") == "PASS"
    issste_ok = issste.get("ok_8_8")
    report["final_verdict"] = (
        "READY_FOR_TAG" if phase_a_ok and issste_ok and report["phases"].get("orchestrator", {}).get("status") == "success" else "BLOCKED"
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    out_report = Path(f"/data/outputs/{args.session}/_JOB_FULL_GENERATION_REPORT.json")
    out_report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[REPORT] {out_report}")

    if report["final_verdict"] == "READY_FOR_TAG":
        print("\n[OK] Fase A + ISSSTE en verde. Procede tag v1.x-isapeg-e2e (manual).")
        return 0
    print("\n[FAIL] Job terminó con bloqueos — NO aplicar code freeze.")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
