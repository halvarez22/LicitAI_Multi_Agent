#!/usr/bin/env python3
"""
Invalida análisis stale y lanza re-análisis (analysis_only) para una sesión.

Uso:
  PYTHONPATH=/app python scripts/force_reanalysis_session.py --session vigilancia_issste
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--mode", default="analysis_only", choices=("analysis_only", "full"))
    args = ap.parse_args()

    from app.agents.mcp_context import MCPContextManager
    from app.agents.orchestrator import OrchestratorAgent
    from app.api.deps import get_connected_memory
    from app.contracts.agent_contracts import AgentInput
    from app.services.session_bases_analysis_invalidation import force_invalidate_analysis_artifacts

    memory = await get_connected_memory()
    ctx = MCPContextManager(memory)
    audit = await force_invalidate_analysis_artifacts(
        memory, args.session, reason="manual_force_reanalysis"
    )
    print("invalidation:", json.dumps(audit, ensure_ascii=False, indent=2))

    state = await memory.get_session(args.session) or {}
    company_data = dict(state.get("company_data") or {})
    company_data["mode"] = args.mode
    orch = OrchestratorAgent(ctx)
    agent_input = AgentInput(
        session_id=args.session,
        job_id=str(uuid.uuid4()),
        mode=args.mode,
        company_id=state.get("company_id"),
        company_data=company_data,
        resume_generation=False,
    )
    print(f"starting orchestrator mode={args.mode} …")
    result = await orch.process(args.session, agent_input.model_dump())
    print("orchestrator_status:", result.get("status"))
    print("message:", result.get("message", "")[:200])

    fresh = await memory.get_session(args.session) or {}
    cml = fresh.get("compliance_master_list") or {}
    if isinstance(cml, dict):
        print(
            "compliance_counts:",
            len(cml.get("administrativo") or []),
            len(cml.get("tecnico") or []),
            len(cml.get("formatos") or []),
        )
    snap = fresh.get("bases_analysis_snapshot") or {}
    print("snapshot:", json.dumps(snap, ensure_ascii=False))
    await memory.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
