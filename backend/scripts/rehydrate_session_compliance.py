#!/usr/bin/env python3
"""
Rehidrata compliance_master_list en una sesión dañada (sin re-ejecutar map-reduce).

Uso:
  python scripts/rehydrate_session_compliance.py --session isapeg
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.agents.orchestrator import _persist_compliance_recovery_if_needed
from app.agents.orchestrator import _compliance_list_from_session
from app.memory.factory import MemoryAdapterFactory


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    state = await memory.get_session(args.session) or {}
    before = _compliance_list_from_session(state)
    state = await _persist_compliance_recovery_if_needed(memory, args.session, state)
    after = _compliance_list_from_session(state)
    print(
        json.dumps(
            {
                "session_id": args.session,
                "had_list_before": bool(before),
                "recovered": bool(after),
                "source": state.get("compliance_recovery_source"),
                "counts": {
                    k: len(after.get(k) or [])
                    for k in ("administrativo", "tecnico", "formatos")
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
