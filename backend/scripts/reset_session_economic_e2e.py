#!/usr/bin/env python3
"""
Reinicia solo economía + expediente en disco para una corrida E2E manual por UI.

Conserva: análisis, compliance, Go/No-Go, dictamen, bases PDF, perfil corporativo.
Limpia: economic_proposal, MPS, cola de generación, archivos en /data/outputs.

Uso (contenedor backend):
  python scripts/reset_session_economic_e2e.py --session isapeg
  python scripts/reset_session_economic_e2e.py --session isapeg --keep-user-prices
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


async def reset_session_economic_e2e(
    session_id: str,
    *,
    keep_user_prices: bool = False,
) -> dict:
    from app.services.generated_outputs_cleanup import clear_generated_outputs_for_session
    from app.memory.factory import MemoryAdapterFactory

    disk = await clear_generated_outputs_for_session(session_id, reset_session=True)

    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    try:
        state = await memory.get_session(session_id) or {}
        if not state:
            raise ValueError(f"Sesión no encontrada: {session_id}")

        tasks = [
            t
            for t in (state.get("tasks_completed") or [])
            if isinstance(t, dict)
            and (t.get("task") or "")
            not in (
                "economic_proposal",
                "stage_completed:economic",
                "technical_writing_COMPLETED",
                "formats_generation_COMPLETED",
                "stage_completed:compranet_pack",
            )
        ]
        state["tasks_completed"] = tasks
        state.pop("master_proposal_state", None)
        state.pop("generation_state", None)
        state.pop("compranet_packaging", None)
        state.pop("last_document_fill_quality_waiting_hints", None)
        state.pop("last_document_quality_waiting_hints", None)

        if not keep_user_prices:
            state.pop("economic_user_inputs", None)
            state.pop("economic_user_overrides", None)

        pending = [
            q
            for q in (state.get("pending_questions") or [])
            if str(q.get("type") or "")
            not in ("economic_price", "economic_validation_blocking")
        ]
        state["pending_questions"] = pending
        state["current_question_index"] = 0

        await memory.save_session(session_id, state)
        return {
            "session_id": session_id,
            "disk_cleanup": disk,
            "economic_reset": True,
            "kept_user_prices": keep_user_prices,
            "remaining_tasks": [t.get("task") for t in tasks],
        }
    finally:
        await memory.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reinicio parcial para E2E: chat económico + generación completa"
    )
    parser.add_argument("--session", required=True, help="ID de sesión (ej. isapeg)")
    parser.add_argument(
        "--keep-user-prices",
        action="store_true",
        help="No borrar economic_user_inputs (reutilizar precios ya capturados en chat)",
    )
    args = parser.parse_args()
    result = asyncio.run(
        reset_session_economic_e2e(
            args.session,
            keep_user_prices=args.keep_user_prices,
        )
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
