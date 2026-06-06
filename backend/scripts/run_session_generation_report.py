#!/usr/bin/env python3
"""
Lanza generation_only para una sesión y emite reporte de regresión.

Uso (contenedor):
  PYTHONPATH=/app python scripts/run_session_generation_report.py unaq-2026_paneles_solares
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.api.deps import get_connected_memory
from app.services.document_candidate_list_service import build_formats_panel_consolidated
from app.services.formats_coverage_gate import count_panel_admin_generar


def _collect_expected_generar(panel: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for bk in (
        "sobre_1_tecnico",
        "sobre_2_economico",
        "requisitos_legales",
        "otros_requisitos_criticos",
    ):
        for row in panel.get(bk) or []:
            if str(row.get("tipo_accion_final") or row.get("tipo") or "") != "generar":
                continue
            name = str(row.get("nombre_canonico") or row.get("nombre") or "").strip()
            if name:
                out.append(name)
    return out


def _load_indice(session_id: str) -> List[Dict[str, Any]]:
    for base in (Path("/data/outputs") / session_id, Path("scratch/outputs") / session_id):
        path = base / "_compranet_validated" / "INDICE_ENTREGA.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return list(data.get("files") or [])
            except Exception:
                return []
    return []


def _formats_task(state: Dict[str, Any]) -> Dict[str, Any]:
    for task in reversed(state.get("tasks_completed") or []):
        if isinstance(task, dict) and task.get("task") == "formats_generation_COMPLETED":
            return task.get("result") or {}
    return {}


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    company_id = str(state.get("company_id") or "").strip()
    if not company_id:
        print("ERROR: sesión sin company_id")
        sys.exit(1)

    # Forzar corrida completa de writers (no saltar etapas «done»).
    state.pop("generation_state", None)
    await mem.save_session(session_id, {"generation_state": None})

    ctx = MCPContextManager(mem)
    orch = OrchestratorAgent(ctx)
    started = datetime.now(timezone.utc)
    print(f"=== GENERACIÓN | {session_id} | {started.isoformat()} ===")
    print(f"company_id={company_id}")

    result = await orch.process(
        session_id,
        {
            "company_id": company_id,
            "mode": "generation_only",
            "resume_generation": False,
            "correlation_id": f"regression_report_{uuid.uuid4().hex[:8]}",
        },
    )

    finished = datetime.now(timezone.utc)
    elapsed_s = int((finished - started).total_seconds())
    state = await mem.get_session(session_id) or {}
    panel = await build_formats_panel_consolidated(mem, session_id, state)
    expected_all = _collect_expected_generar(panel)
    expected_admin = count_panel_admin_generar(panel)
    indice = _load_indice(session_id)
    formats_res = _formats_task(state)
    fmt_docs = list(formats_res.get("documentos") or [])
    skipped = list(formats_res.get("generation_skipped") or [])
    stop = (result.get("orchestrator_decision") or state.get("last_orchestrator_decision") or {}).get(
        "stop_reason"
    )
    status = str(result.get("status") or "")

    admin_dir = Path("/data/outputs") / session_id / "3.documentos administrativos"
    admin_files = sorted(admin_dir.glob("*.docx")) if admin_dir.is_dir() else []

    print(f"\n--- RESULTADO ORQUESTADOR ({elapsed_s}s) ---")
    print(f"status={status}")
    print(f"stop_reason={stop}")
    print(f"message={str(result.get('message') or result.get('chatbot_message') or '')[:300]}")

    print(f"\n--- FORMATOS ADMIN ---")
    print(f"panel_generar_total={len(expected_all)} panel_admin={expected_admin}")
    print(f"formats_materializados={len(fmt_docs)} skipped={len(skipped)}")
    for i, d in enumerate(fmt_docs, 1):
        if isinstance(d, dict):
            route = d.get("materialization_route") or "n/d"
            print(f"  {i:02d}. {str(d.get('nombre') or '')[:90]} [{route}]")
    if skipped:
        print("  Omitidos:")
        for s in skipped[:10]:
            if isinstance(s, dict):
                print(f"    - {s.get('nombre', '')[:70]} ({s.get('reason')})")

    print(f"\n--- CARPETA ADMIN EN DISCO ({len(admin_files)} docx) ---")
    for p in admin_files:
        print(f"  - {p.name} ({p.stat().st_size} bytes)")

    print(f"\n--- ÍNDICE COMPRANET ({len(indice)} archivos) ---")
    by_sobre: Dict[str, int] = {}
    for ent in indice:
        sb = str(ent.get("sobre") or "?")
        by_sobre[sb] = by_sobre.get(sb, 0) + 1
        print(
            f"  [{sb}] {str(ent.get('nombre_entrega') or ent.get('path') or '')[:85]}"
        )
    print(f"por_sobre={by_sobre}")

    # Criterio regresión anulada
    admin_ok = len(fmt_docs) >= max(11, int(expected_admin * 0.85))
    indice_ok = len(indice) >= 14
    final_ok = stop == "FINAL_OK" and status in ("success", "partial")
    regression_cleared = admin_ok and indice_ok and final_ok

    print(f"\n--- VEREDICTO REGRESIÓN ---")
    print(f"admin_count_ok={admin_ok} ({len(fmt_docs)}/{expected_admin})")
    print(f"indice_ok={indice_ok} ({len(indice)} archivos)")
    print(f"final_ok={final_ok} (stop={stop})")
    print(f"REGRESION_ANULADA={'SI' if regression_cleared else 'NO'}")
    sys.exit(0 if regression_cleared else 2)


if __name__ == "__main__":
    asyncio.run(main())
