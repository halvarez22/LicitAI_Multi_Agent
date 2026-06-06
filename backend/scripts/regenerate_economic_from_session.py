#!/usr/bin/env python3
"""
Refresca validaciones económicas y regenera documentos del economic_writer.

Uso:
  PYTHONPATH=/app python scripts/regenerate_economic_from_session.py <session_id>
"""
from __future__ import annotations

import asyncio
import json
import sys

from app.agents.economic_writer import EconomicWriterAgent
from app.agents.mcp_context import MCPContextManager
from app.api.deps import get_connected_memory
from app.contracts.agent_contracts import AgentInput, AgentStatus
from app.economic_validation.service import refresh_economic_validations_for_session
from app.services.economic_tabular_ingest_sync import sync_economic_pending_after_tabular_ingest


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    if not state:
        print(f"Sesión no encontrada: {session_id}")
        sys.exit(1)

    company_id = str(state.get("company_id") or state.get("selected_company_id") or "")
    mp = state.get("master_profile") or {}
    if not mp and company_id:
        co = await mem.get_company(company_id)
        if isinstance(co, dict):
            mp = co.get("master_profile") or {}

    sync = await sync_economic_pending_after_tabular_ingest(mem, session_id)
    print("tabular_sync", json.dumps(sync, ensure_ascii=False))

    try:
        val = await refresh_economic_validations_for_session(mem, session_id)
        print(
            "refresh_validations",
            f"status={getattr(val, 'status', val)}",
            f"blocking={getattr(val, 'blocking_issues', None)}",
        )
    except Exception as exc:
        print(f"refresh_validations_warn: {exc}")

    state = await mem.get_session(session_id) or {}
    mps = state.get("master_proposal_state") or {}
    items = mps.get("items") or []
    print(
        "mps_summary",
        f"items={len(items)}",
        f"total_base={mps.get('total_base')}",
        f"grand_total={mps.get('grand_total')}",
    )

    try:
        rows = await mem.get_line_items_for_session(session_id)
        cmyt = [
            r
            for r in (rows or [])
            if "cmyt" in str((r.get("extra") or {}).get("source_filename") or "").lower()
            or "membretada" in str((r.get("extra") or {}).get("source_filename") or "").lower()
        ]
        print(f"line_items_total={len(rows or [])} cmyt_related={len(cmyt)}")
        for r in cmyt[:3]:
            extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
            print(
                "  ",
                extra.get("source_filename"),
                "precio=",
                r.get("precio_unitario"),
                "concepto=",
                (r.get("concepto_raw") or r.get("concepto_norm") or "")[:60],
            )
    except Exception as exc:
        print(f"line_items_warn: {exc}")

    ctx = MCPContextManager(mem)
    agent_in = AgentInput(
        session_id=session_id,
        company_id=company_id or "default",
        company_data={
            "master_profile": mp,
            "economic_data": mps if mps.get("items") else None,
        },
    )
    writer = EconomicWriterAgent(ctx)
    res = await writer.process(agent_in)
    print(f"economic_writer status={res.status} message={res.message}")
    if res.status != AgentStatus.SUCCESS:
        print(f"error={res.error} data={res.data}")
        sys.exit(2)

    docs = (res.data or {}).get("documentos") or []
    for d in docs:
        if isinstance(d, dict):
            print(
                "doc",
                d.get("nombre"),
                d.get("materialization_route") or d.get("tipo"),
                d.get("ruta"),
            )
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
