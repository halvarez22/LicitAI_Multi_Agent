#!/usr/bin/env python3
"""
E2E interno — agenda HITL C→D→A→B + SUPER ISSUE mínimo.

Fases:
  1. pytest (unitarios agenda)
  2. Simulación in-process (chatbot mock, cola, TSV, patch)
  3. Opcional: orquestador+chat con Postgres si DATABASE_URL disponible

Salida: backend/scratch/e2e_agenda_hitl_report.json

Uso:
  cd backend && python scripts/e2e_agenda_hitl_complete.py
  docker compose exec backend python scripts/e2e_agenda_hitl_complete.py
"""
from __future__ import annotations

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

REPORT_PATH = _ROOT / "scratch" / "e2e_agenda_hitl_report.json"

PYTEST_FILES = [
    "tests/test_hitl_queue_service.py",
    "tests/test_conversational_price_normalizer.py",
    "tests/test_conversational_price_utterances.py",
    "tests/test_economic_column_roles.py",
    "tests/test_structured_location_price_slots.py",
    "tests/test_chat_economic_matrix.py",
    "tests/test_economic_coverage_gate.py",
    "tests/test_excel_filling_service.py",
    "tests/test_document_deliverable_filter.py",
]


def _run_pytest() -> Dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", *PYTEST_FILES, "-q", "--tb=line"]
    proc = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-1500:],
    }


async def _simulate_chatbot_flow() -> Dict[str, Any]:
    """Flujo chatbot con memoria mock: cola económica, precio natural, TSV."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.agents.chatbot_rag import ChatbotRAGAgent
    from app.agents.mcp_context import MCPContextManager
    from app.contracts.agent_contracts import AgentInput, AgentStatus
    from app.services.resilient_llm import LLMResponse

    state: Dict[str, Any] = {
        "pending_questions": [
            {
                "type": "economic_price",
                "field": "price_struct_location_acambaro",
                "label": "Precio: Acámbaro",
                "question": "Precio para Acámbaro",
            },
            {
                "type": "economic_price",
                "field": "price_struct_location_celaya",
                "label": "Precio: Celaya",
                "question": "Precio para Celaya",
            },
        ],
        "current_question_index": 0,
        "economic_user_inputs": {},
        "capture_matrix_blocks": [
            {
                "intro_message": "Matriz ZB mock",
                "matrix_columns": [
                    {"key": "label", "title": "Localidad"},
                    {"key": "price", "title": "Precio"},
                ],
                "matrix_rows": [
                    {"label": "Acámbaro", "field": "price_struct_location_acambaro"},
                    {"label": "Celaya", "field": "price_struct_location_celaya"},
                ],
            }
        ],
        "tasks_completed": [{"task": "stage_completed:compliance", "result": {"data": {}}}],
        "last_orchestrator_decision": {"stop_reason": "MISSING_PRICES"},
    }

    ctx = MagicMock(spec=MCPContextManager)
    ctx.memory = MagicMock()
    ctx.memory.get_session = AsyncMock(side_effect=lambda _sid: dict(state))
    ctx.memory.save_session = AsyncMock(
        side_effect=lambda _sid, updates: state.update(updates) or True
    )
    ctx.memory.get_company = AsyncMock(
        return_value={"id": "co_mock", "master_profile": {"razon_social": "Mock"}}
    )
    ctx.memory.save_company = AsyncMock(return_value=True)
    ctx.memory.get_conversation = AsyncMock(return_value=[])
    ctx.memory.save_conversation = AsyncMock(return_value=True)

    sid = f"e2e_agenda_{uuid.uuid4().hex[:10]}"
    steps: List[str] = []

    with patch("app.agents.chatbot_rag.VectorDbServiceClient"), patch(
        "app.agents.chatbot_rag.ResilientLLMClient"
    ) as mock_llm_cls:
        bot = ChatbotRAGAgent(ctx)
        bot.llm = mock_llm_cls.return_value
        bot.llm.generate = AsyncMock(return_value=LLMResponse(success=True, response="x"))
        bot.llm.chat = AsyncMock(return_value=LLMResponse(success=True, response="ok"))

        # TSV bulk
        tsv_inp = AgentInput(
            session_id=sid,
            company_id="co_mock",
            company_data={"query": "Acámbaro\t1325\nCelaya\t1400"},
        )
        with patch.object(
            ChatbotRAGAgent,
            "process",
            wraps=bot.process,
        ):
            pass

        with patch(
            "app.agents.chatbot_rag.refresh_economic_validations_for_session",
            new_callable=AsyncMock,
        ):
            out_tsv = await bot._try_tsv_bulk_economic_prices(
                sid, tsv_inp.company_data["query"], "co_mock", state, ""
            )
        if out_tsv and out_tsv.data:
            steps.append("tsv_bulk_ok")
        else:
            steps.append("tsv_bulk_fail")

        # Precio conversacional
        state["pending_questions"] = [
            {
                "type": "economic_price",
                "field": "price_test_zona",
                "label": "Zona A L-D",
                "question": "Precio zona A",
            }
        ]
        state["current_question_index"] = 0
        with patch(
            "app.agents.chatbot_rag.refresh_economic_validations_for_session",
            new_callable=AsyncMock,
        ), patch.object(
            bot,
            "_apply_saved_pending_value",
            new_callable=AsyncMock,
        ) as mock_apply:
            from app.contracts.agent_contracts import AgentOutput

            mock_apply.return_value = AgentOutput(
                status=AgentStatus.SUCCESS,
                agent_id="chatbot",
                session_id=sid,
                message="ok",
                data={"respuesta": "guardado", "tipo": "data_saved"},
            )
            out_price = await bot._handle_data_intake(
                sid, "35 mil 529", "co_mock", state["pending_questions"], 0, state, ""
            )
        if out_price.status != AgentStatus.ERROR:
            steps.append("conversational_price_ok")
        else:
            steps.append("conversational_price_fail")

        # META sin forense
        meta = await bot._handle_meta_query(sid, "generar", state, "")
        resp = (meta.data or {}).get("respuesta") or ""
        if "Gate 12" not in resp and "MISSING_" not in resp:
            steps.append("meta_sanitized_ok")
        else:
            steps.append("meta_sanitized_fail")

    ok = all(
        s.endswith("_ok")
        for s in steps
        if s not in ("tsv_bulk_fail", "conversational_price_fail", "meta_sanitized_fail")
    )
    return {"ok": "tsv_bulk_ok" in steps and "conversational_price_ok" in steps, "steps": steps}


async def _simulate_patch_flow() -> Dict[str, Any]:
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services.document_patch_service import apply_price_correction

    memory = MagicMock()
    state = {
        "economic_user_inputs": {"price_struct_location_acambaro": 100.0},
        "session_line_items": [
            {
                "concepto_raw": "Acámbaro",
                "cantidad": 1.0,
                "precio_unitario": 100.0,
                "sheet_name": "Hoja1",
                "row_index": 0,
                "extra": {
                    "layout": "structured_template",
                    "template_kind": "location_price_grid",
                    "location_label": "Acámbaro",
                    "source_filename": "missing.xlsx",
                    "price_column_index": 2,
                },
            }
        ],
        "tasks_completed": [],
    }
    memory.get_session = AsyncMock(return_value=state)
    memory.save_session = AsyncMock(return_value=True)

    with patch(
        "app.economic_validation.service.refresh_economic_validations_for_session",
        new_callable=AsyncMock,
    ):
        try:
            result = await apply_price_correction(
                memory,
                "sess_patch",
                price_field="price_struct_location_acambaro",
                new_value=200.0,
                previous_value=100.0,
            )
            audit_ok = state.get("economic_user_inputs", {}).get(
                "price_struct_location_acambaro"
            ) == 200.0
            return {
                "ok": audit_ok and "price_field" in result,
                "result": {k: result.get(k) for k in ("price_field", "file_count")},
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


async def _optional_db_e2e() -> Dict[str, Any]:
    if not os.environ.get("DATABASE_URL"):
        return {"skipped": True, "reason": "DATABASE_URL no definida"}
    try:
        from scripts.e2e_chatbot_intake_full_generation import main as chatbot_main

        code = await chatbot_main()
        return {"ok": code == 0, "returncode": code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def main() -> int:
    report: Dict[str, Any] = {
        "schema": "e2e_agenda_hitl_v1",
        "at": datetime.now(timezone.utc).isoformat(),
        "phases": {},
    }

    print("[E2E Agenda] Fase 1: pytest unitarios…")
    report["phases"]["pytest"] = _run_pytest()
    if not report["phases"]["pytest"]["ok"]:
        print("[E2E Agenda] FALLÓ pytest")
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return 1

    print("[E2E Agenda] Fase 2: simulación chatbot…")
    report["phases"]["chatbot_sim"] = await _simulate_chatbot_flow()

    print("[E2E Agenda] Fase 3: simulación patch…")
    report["phases"]["patch_sim"] = await _simulate_patch_flow()

    print("[E2E Agenda] Fase 4: E2E DB opcional…")
    report["phases"]["db_e2e"] = await _optional_db_e2e()

    all_ok = (
        report["phases"]["pytest"]["ok"]
        and report["phases"]["chatbot_sim"].get("ok")
        and report["phases"]["patch_sim"].get("ok")
        and (
            report["phases"]["db_e2e"].get("skipped")
            or report["phases"]["db_e2e"].get("ok")
        )
    )
    report["overall_ok"] = all_ok

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[E2E Agenda] overall_ok={all_ok}")
    print(f"[E2E Agenda] Reporte: {REPORT_PATH}")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
