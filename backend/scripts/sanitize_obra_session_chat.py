#!/usr/bin/env python3
"""
Sanitiza cola HITL y etiquetas de inventario para sesiones de obra.

Uso:
  PYTHONPATH=/app python scripts/sanitize_obra_session_chat.py SESSION_ID
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def main(session_id: str) -> int:
    from app.api.deps import get_connected_memory
    from app.services.hitl_queue_service import normalize_pending_queue, sanitize_chat_pending_questions
    from app.services.obra_chat_queue_policy import enrich_inventory_payload_for_ui

    mem = await get_connected_memory()
    try:
        st = await mem.get_session(session_id) or {}
        before = list(st.get("pending_questions") or [])
        after = sanitize_chat_pending_questions(before, st)
        after = normalize_pending_queue(after)

        inv = st.get("document_inventory")
        inv_out = enrich_inventory_payload_for_ui(inv) if isinstance(inv, dict) else inv

        updates = {
            "pending_questions": after,
            "current_question_index": 0,
        }
        if inv_out:
            updates["document_inventory"] = inv_out

        await mem.save_session(session_id, updates)
        print(
            json.dumps(
                {
                    "session_id": session_id,
                    "pending_before": len(before),
                    "pending_after": len(after),
                    "removed": [q.get("field") or q.get("question_id") for q in before if q not in after],
                    "inventory_items": len((inv_out or {}).get("items") or []),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        await mem.disconnect()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"
    raise SystemExit(asyncio.run(main(sid)))
