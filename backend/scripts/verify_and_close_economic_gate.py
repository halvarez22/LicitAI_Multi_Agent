#!/usr/bin/env python3
"""Valida gate económico sobre archivos reales y cierra sesión si pasa."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.api.deps import get_connected_memory
from app.services.document_fill_quality_gate import validate_generated_documents_fill


def _scan_econ(session_id: str) -> List[Dict[str, Any]]:
    base = Path("/data/outputs") / session_id / "2.propuesta_economica"
    out: List[Dict[str, Any]] = []
    routes = {
        "ANEXO_AE": "deterministic",
        "TABLA_PRECIOS": "deterministic",
        "CARTA_COMPROMISO": "deterministic",
        "ANALISIS_PRECIOS": "deterministic_apu",
    }
    for p in sorted(base.glob("*")):
        if p.suffix.lower() not in (".docx", ".xlsx"):
            continue
        route = "deterministic"
        for k, v in routes.items():
            if k in p.name.upper():
                route = v
                break
        out.append(
            {
                "nombre": p.stem,
                "ruta": str(p),
                "tipo": "economico",
                "materialization_route": route,
                "template_id": "anexo_economico"
                if "AE" in p.name.upper()
                else "tabla_precios"
                if "TABLA" in p.name.upper()
                else "carta_compromiso"
                if "CARTA" in p.name.upper()
                else "apu",
            }
        )
    return out


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    profile = state.get("master_profile") or {}
    docs = _scan_econ(session_id)

    resumen: Dict[str, Any] = {}
    for task in reversed(state.get("tasks_completed") or []):
        if isinstance(task, dict) and task.get("task") == "economic_proposal":
            payload = task.get("result") or {}
            data = payload.get("data") if isinstance(payload, dict) else {}
            if isinstance(data, dict):
                resumen = data.get("resumen") or data.get("resumen_economico") or {}
                break

    gate = validate_generated_documents_fill(
        stage="economic",
        generated_documents=docs,
        master_profile=profile,
        provenance_context={
            "source": "economic_writer",
            "confidence": 0.95,
            "economic_resumen": {
                "subtotal": resumen.get("subtotal"),
                "iva": resumen.get("iva"),
                "total": resumen.get("total"),
            },
        },
    )
    print(f"docs={len(docs)} validation_passed={gate.get('validation_passed')} blocking={gate.get('blocking_count')}")
    for issue in gate.get("issues") or []:
        if issue.get("severity") == "block":
            print(f"  BLOCK {issue.get('document_id')} {issue.get('field_key')} ({issue.get('error_type')})")

    if not gate.get("validation_passed"):
        sys.exit(2)

    await mem.save_session(
        session_id,
        {
            "pending_questions": [],
            "current_question_index": 0,
            "last_document_fill_quality_waiting_hints": None,
        },
    )

    gen_state = state.get("generation_state") or {}
    for job in gen_state.get("jobs") or []:
        if isinstance(job, dict) and job.get("id") in ("economic_writer", "packager", "delivery"):
            job["status"] = "pending" if job.get("id") != "economic_writer" else "done"

    await mem.save_session(session_id, {"generation_state": gen_state})

    company_id = str(state.get("company_id") or "")
    orch = OrchestratorAgent(MCPContextManager(mem))
    result = await orch.process(
        session_id,
        {
            "company_id": company_id,
            "mode": "generation_only",
            "resume_generation": True,
        },
    )
    stop = (result.get("orchestrator_decision") or {}).get("stop_reason")
    print(f"orchestrator status={result.get('status')} stop={stop}")
    sys.exit(0 if stop == "FINAL_OK" else 3)


if __name__ == "__main__":
    asyncio.run(main())
