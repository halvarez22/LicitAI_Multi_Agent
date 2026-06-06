#!/usr/bin/env python3
"""Cierra sesión en FINAL_OK tras validar gate económico (sin re-generar writers)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.api.deps import get_connected_memory
from app.services.document_fill_quality_gate import validate_generated_documents_fill


def _scan_econ(session_id: str) -> List[Dict[str, Any]]:
    base = Path("/data/outputs") / session_id / "2.propuesta_economica"
    out: List[Dict[str, Any]] = []
    for p in sorted(base.glob("*")):
        if p.suffix.lower() not in (".docx", ".xlsx"):
            continue
        upper = p.name.upper()
        if "AE" in upper:
            tid, route = "anexo_economico", "deterministic"
        elif "TABLA" in upper:
            tid, route = "tabla_precios", "deterministic"
        elif "CARTA" in upper:
            tid, route = "carta_compromiso", "deterministic"
        else:
            tid, route = "apu", "deterministic_apu"
        out.append(
            {
                "nombre": p.stem,
                "ruta": str(p),
                "tipo": tid,
                "template_id": tid,
                "materialization_route": route,
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
        if not isinstance(task, dict):
            continue
        if task.get("task") in ("economic_proposal", "stage_completed:economic"):
            payload = task.get("result") or {}
            data = payload.get("data") if isinstance(payload, dict) else payload
            if isinstance(data, dict):
                resumen = (
                    data.get("resumen")
                    or data.get("resumen_economico")
                    or (data.get("resumen_economico") if isinstance(data.get("resumen_economico"), dict) else {})
                )
                if resumen:
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
    print(f"economic_gate passed={gate.get('validation_passed')} blocking={gate.get('blocking_count')}")
    if not gate.get("validation_passed"):
        for issue in gate.get("issues") or []:
            if issue.get("severity") == "block":
                print(f"  BLOCK {issue.get('document_id')} {issue.get('field_key')}")
        sys.exit(2)

    gen_state = state.get("generation_state") or {}
    for job in gen_state.get("jobs") or []:
        if isinstance(job, dict):
            job["status"] = "done"

    await mem.save_session(
        session_id,
        {
            "pending_questions": [],
            "current_question_index": 0,
            "last_document_fill_quality_waiting_hints": None,
            "generation_state": gen_state,
            "last_orchestrator_decision": {
                "stop_reason": "FINAL_OK",
                "aggregate_health": "healthy",
                "next_steps": [],
            },
        },
    )
    print("session_closed stop_reason=FINAL_OK")
    indice = Path("/data/outputs") / session_id / "_compranet_validated" / "INDICE_ENTREGA.json"
    if indice.is_file():
        n = len(json.loads(indice.read_text(encoding="utf-8")).get("files") or [])
        print(f"compranet_indice={n}")


if __name__ == "__main__":
    asyncio.run(main())
