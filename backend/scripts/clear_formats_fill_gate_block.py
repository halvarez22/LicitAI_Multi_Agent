#!/usr/bin/env python3
"""
Limpia bloqueos obsoletos de formatos en sesión (pending_questions + hints + cola).

El gate en disco puede estar OK pero el chat sigue mostrando «Pregunta 1 de 2»
con mensajes de Constancia/DC-4 o «15 de 39» de una corrida anterior.

Uso:
  python scripts/clear_formats_fill_gate_block.py isapeg_servicios_de_limpieza
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DROP_FIELDS = frozenset(
    {
        "formats_completeness_gate",
        "document_fill_quality_gate",
        "quality.fill.review",
    }
)
_DROP_TYPES = frozenset(
    {
        "formats_completeness_gate_blocking",
        "document_fill_quality_gate_blocking",
        "quality_validation_blocking",
    }
)


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "isapeg_servicios_de_limpieza"
    from app.api.deps import get_connected_memory

    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    before = len(state.get("pending_questions") or [])
    state["pending_questions"] = [
        q
        for q in (state.get("pending_questions") or [])
        if isinstance(q, dict)
        and str(q.get("field") or "") not in _DROP_FIELDS
        and str(q.get("type") or "") not in _DROP_TYPES
    ]
    state["current_question_index"] = 0
    state.pop("last_document_fill_quality_waiting_hints", None)
    gen = state.get("generation_state") if isinstance(state.get("generation_state"), dict) else {}
    jobs = gen.get("jobs") if isinstance(gen.get("jobs"), list) else []
    for step in jobs:
        if isinstance(step, dict) and str(step.get("id") or "") == "formats":
            if str(step.get("status") or "").lower() == "blocked":
                step["status"] = "pending"
    gen["status"] = "paused"
    state["generation_state"] = gen
    decision = state.get("last_orchestrator_decision")
    if isinstance(decision, dict) and str(decision.get("stop_reason") or "").startswith(
        "INCOMPLETE_FORMATS"
    ):
        state.pop("last_orchestrator_decision", None)
    await mem.save_session(session_id, state)
    await mem.disconnect()
    after = len(state.get("pending_questions") or [])
    print(
        f"OK: sesión {session_id} — pending {before}→{after}, hints limpiados, "
        "formats desbloqueado. Refresca UI y pulsa Generar (backend debe tener código reciente)."
    )


if __name__ == "__main__":
    asyncio.run(main())
