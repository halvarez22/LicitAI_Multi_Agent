#!/usr/bin/env python3
"""Reanuda empaquetado CompraNet usando archivos ya materializados en disco."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.agents.mcp_context import MCPContextManager
from app.agents.orchestrator import OrchestratorAgent
from app.api.deps import get_connected_memory


def _scan_stage_docs(session_id: str, subdir: str, tipo: str) -> List[Dict[str, Any]]:
    root = Path("/data/outputs") / session_id / subdir
    if not root.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for p in sorted(root.glob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".docx", ".xlsx", ".pdf"):
            continue
        out.append(
            {
                "nombre": p.stem.replace("_", " "),
                "ruta": str(p),
                "status": "FINAL",
                "tipo": tipo,
                "materialization_route": "resume_from_disk",
            }
        )
    return out


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    company_id = str(state.get("company_id") or "").strip()
    if not company_id:
        print("ERROR: sin company_id")
        sys.exit(1)

    admin = _scan_stage_docs(session_id, "3.documentos administrativos", "administrativo")
    tech = _scan_stage_docs(session_id, "1.propuesta tecnica", "tecnico")
    econ = _scan_stage_docs(session_id, "2.propuesta_economica", "economico")

    formats_payload = {
        "documentos": admin,
        "count": len(admin),
        "folder": f"/data/outputs/{session_id}/3.documentos administrativos",
        "resumed_from_disk": True,
    }
    ctx = MCPContextManager(mem)
    await ctx.record_task_completion(session_id, "formats_generation_COMPLETED", formats_payload)
    await ctx.record_task_completion(
        session_id,
        "technical_writing_COMPLETED",
        {"documentos": tech, "count": len(tech)},
    )
    await ctx.record_task_completion(
        session_id,
        "economic_writing_COMPLETED",
        {"documentos": econ, "count": len(econ)},
    )

    gen_state = state.get("generation_state") or {}
    for job in gen_state.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        jid = str(job.get("id") or "")
        if jid in ("formats", "technical", "economic_writer"):
            job["status"] = "done"
        elif jid in ("packager", "delivery"):
            job["status"] = "pending"
    await mem.save_session(session_id, {"generation_state": gen_state, "pending_questions": []})

    orch = OrchestratorAgent(ctx)
    result = await orch.process(
        session_id,
        {
            "company_id": company_id,
            "mode": "generation_only",
            "resume_generation": True,
            "correlation_id": f"resume_pack_{uuid.uuid4().hex[:8]}",
        },
    )
    stop = (result.get("orchestrator_decision") or {}).get("stop_reason")
    indice_path = Path("/data/outputs") / session_id / "_compranet_validated" / "INDICE_ENTREGA.json"
    indice_n = 0
    if indice_path.is_file():
        try:
            indice_n = len(json.loads(indice_path.read_text(encoding="utf-8")).get("files") or [])
        except Exception:
            pass
    print(f"status={result.get('status')} stop={stop}")
    print(f"admin_disk={len(admin)} tech={len(tech)} econ={len(econ)} indice={indice_n}")
    ok = stop == "FINAL_OK" and indice_n >= 14
    print(f"REGRESION_ANULADA={'SI' if ok else 'NO'}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    asyncio.run(main())
