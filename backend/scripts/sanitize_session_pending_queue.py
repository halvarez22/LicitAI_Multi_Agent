"""Sanea ``pending_questions`` en sesiones en vuelo (Ítem C.8)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.api.deps import get_connected_memory
from app.services.hitl_queue_service import normalize_pending_queue


async def _run(session_id: str, *, dry_run: bool) -> int:
    memory = await get_connected_memory()
    state = await memory.get_session(session_id)
    if not isinstance(state, dict):
        print(json.dumps({"success": False, "message": "Sesión no encontrada"}, ensure_ascii=False))
        return 1

    before = list(state.get("pending_questions") or [])
    after = normalize_pending_queue(before)
    report = {
        "success": True,
        "session_id": session_id,
        "dry_run": dry_run,
        "before_count": len(before),
        "after_count": len(after),
        "removed": len(before) - len(after),
    }
    if not dry_run and after != before:
        state["pending_questions"] = after
        if after:
            idx = int(state.get("current_question_index") or 0)
            state["current_question_index"] = max(0, min(idx, len(after) - 1))
        else:
            state["current_question_index"] = 0
        await memory.save_session(session_id, state)
        report["persisted"] = True
    else:
        report["persisted"] = False

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Normaliza cola HITL de una sesión")
    parser.add_argument("session_id", help="ID de sesión")
    parser.add_argument("--dry-run", action="store_true", help="Solo reporte, sin persistir")
    args = parser.parse_args()
    return asyncio.run(_run(args.session_id, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
