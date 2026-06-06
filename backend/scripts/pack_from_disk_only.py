#!/usr/bin/env python3
"""Empaqueta CompraNet directo desde archivos en disco (sin re-ejecutar writers)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from app.agents.mcp_context import MCPContextManager
from app.agents.packager import CompraNetPackager
from app.api.deps import get_connected_memory
from app.contracts.agent_contracts import AgentInput


def _scan_docs(session_id: str, subdir: str, tipo: str) -> List[Dict[str, Any]]:
    root = Path("/data/outputs") / session_id / subdir
    out: List[Dict[str, Any]] = []
    if not root.is_dir():
        return out
    for p in sorted(root.glob("*")):
        if p.is_file() and p.suffix.lower() in (".docx", ".xlsx", ".pdf"):
            out.append({"nombre": p.name, "ruta": str(p), "status": "FINAL", "tipo": tipo})
    return out


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    company_id = str(state.get("company_id") or "")

    admin = _scan_docs(session_id, "3.documentos administrativos", "administrativo")
    tech = _scan_docs(session_id, "1.propuesta tecnica", "tecnico")
    econ = _scan_docs(session_id, "2.propuesta_economica", "economico")

    ctx = MCPContextManager(mem)
    master = state.get("master_profile") or {}
    agent_input = AgentInput(
        session_id=session_id,
        company_id=company_id,
        company_data={
            **master,
            "master_profile": master,
            "licitacion_id": session_id,
            "documentos_generados": {
                "tecnica": tech,
                "administrativa": admin,
                "economica": econ,
            },
        },
        job_id=f"pack_only_{session_id}",
    )

    from app.agents.document_packager import DocumentPackagerAgent

    pack_res = await DocumentPackagerAgent(ctx).process(agent_input)
    pack_data = pack_res.data if hasattr(pack_res, "data") else {}
    print(f"packager_status={getattr(pack_res, 'status', None)} folder={pack_data.get('folder_raiz')}")

    from app.agents.packager import CompraNetPackager, build_pack_session_data_from_outputs

    pack_session = build_pack_session_data_from_outputs(
        session_id,
        pack_data,
        agent_input.company_data,
        session_state=state,
    )
    cn_res = CompraNetPackager().pack(pack_session)
    print(f"compranet_success={cn_res.success} validation={cn_res.validation_passed}")
    print(f"compranet_files={len(cn_res.files or [])}")
    if cn_res.contamination_report:
        cr = cn_res.contamination_report.get("summary") or {}
        print(
            f"forensic_gate blocking={cr.get('blocking_findings')} "
            f"passed={cn_res.contamination_report.get('gate_passed')}"
        )

    if not cn_res.success:
        for err in cn_res.errors[:8]:
            print(f"  ERROR: {err}")
        sys.exit(2)

    indice = Path("/data/outputs") / session_id / "_compranet_validated" / "INDICE_ENTREGA.json"
    if indice.is_file():
        files = json.loads(indice.read_text(encoding="utf-8")).get("files") or []
        print(f"indice_count={len(files)}")
        for ent in files:
            print(f"  [{ent.get('sobre')}] {str(ent.get('nombre_entrega') or '')[:85]}")
        ok = len(files) >= 18 and len(admin) >= 13
        print(f"REGRESION_CANTIDAD_NOMBRES={'SI' if ok else 'NO'}")
        sys.exit(0 if ok else 2)
    print("ERROR: sin INDICE_ENTREGA.json")
    sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
