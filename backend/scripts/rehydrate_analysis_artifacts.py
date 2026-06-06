#!/usr/bin/env python3
"""
Rehidrata artefactos de análisis (candidatos, hitos, junta) sin borrar HITL ni generación.

Uso:
  PYTHONPATH=/app python scripts/rehydrate_analysis_artifacts.py --session vigilancia_issste
  PYTHONPATH=/app python scripts/rehydrate_analysis_artifacts.py --all-reference
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

REFERENCE_SESSIONS = (
    "isapeg_servicios_de_limpieza",
    "unaq-2026_paneles_solares",
    "vigilancia_issste",
)


async def _run_one(session_id: str, *, company_id: str | None, force_junta: bool) -> dict:
    from app.api.deps import get_connected_memory
    from app.services.analysis_artifacts_rehydrate_service import (
        rehydrate_analysis_artifacts,
    )

    memory = await get_connected_memory()
    try:
        before = await memory.get_session(session_id) or {}
        preserved_before = {
            "economic_user_inputs": len(before.get("economic_user_inputs") or {}),
            "generation_state": 1 if before.get("generation_state") else 0,
        }
        result = await rehydrate_analysis_artifacts(
            memory,
            session_id,
            company_id=company_id,
            force_junta_refresh=force_junta,
            commit_snapshot=True,
        )
        after = await memory.get_session(session_id) or {}
        preserved_after = {
            "economic_user_inputs": len(after.get("economic_user_inputs") or {}),
            "generation_state": 1 if after.get("generation_state") else 0,
        }
        out = result.to_dict()
        out["preserved_economic_inputs"] = preserved_after["economic_user_inputs"]
        out["preserved_generation_state"] = preserved_after["generation_state"]
        out["preserved_unchanged"] = preserved_before == preserved_after
        return out
    finally:
        await memory.disconnect()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Rehidrata artefactos post-análisis")
    parser.add_argument("--session", action="append", dest="sessions", default=[])
    parser.add_argument(
        "--all-reference",
        action="store_true",
        help="Ejecutar en las 3 sesiones referencia del sprint",
    )
    parser.add_argument("--company-id", default=None)
    parser.add_argument(
        "--force-junta",
        action="store_true",
        help="Forzar recálculo de preguntas junta",
    )
    args = parser.parse_args()

    targets: List[str] = list(args.sessions)
    if args.all_reference:
        targets.extend(REFERENCE_SESSIONS)
    targets = sorted(set(t for t in targets if t))
    if not targets:
        parser.error("Indica --session ID o --all-reference")

    results = []
    exit_code = 0
    for sid in targets:
        row = await _run_one(sid, company_id=args.company_id, force_junta=args.force_junta)
        results.append(row)
        if not row.get("success"):
            exit_code = 1
        print(json.dumps(row, ensure_ascii=False, indent=2))

    if len(results) > 1:
        print(json.dumps({"summary": {"total": len(results), "ok": sum(1 for r in results if r.get("success"))}}, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
