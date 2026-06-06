#!/usr/bin/env python3
"""
Captura conteos actuales y escribe baseline JSON (anonimizado) para sesiones referencia.

Uso:
  PYTHONPATH=/app python scripts/capture_reference_baseline.py --session vigilancia_issste
  PYTHONPATH=/app python scripts/capture_reference_baseline.py --all-reference --dry-run
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

from app.services.reference_session_baseline import (
    REFERENCE_SESSION_IDS,
    baseline_path_for_session,
    build_baseline_document,
    extract_session_counts,
)


async def capture(session_id: str, *, dry_run: bool) -> dict:
    from app.api.deps import get_connected_memory

    memory = await get_connected_memory()
    try:
        state = await memory.get_session(session_id)
        if not state:
            raise SystemExit(f"Sesión no encontrada: {session_id}")
        counts = extract_session_counts(state)
        doc = build_baseline_document(
            session_id,
            counts,
            note="Capturado por capture_reference_baseline.py",
        )
        if not dry_run:
            path = baseline_path_for_session(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return doc
    finally:
        await memory.disconnect()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", action="append", dest="sessions", default=[])
    ap.add_argument("--all-reference", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    targets = list(args.sessions)
    if args.all_reference:
        targets.extend(REFERENCE_SESSION_IDS)
    targets = sorted(set(t for t in targets if t))
    if not targets:
        ap.error("Indica --session o --all-reference")

    for sid in targets:
        doc = await capture(sid, dry_run=args.dry_run)
        print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
