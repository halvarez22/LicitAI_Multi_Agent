#!/usr/bin/env python3
"""
Auditoría universal de contenido en entrega CompraNet.

Uso:
  PYTHONPATH=. python scripts/audit_delivery_content.py <session_id> [--json out.json]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.api.deps import get_connected_memory
from app.services.delivery_content_audit import audit_delivery_files, run_forensic_contamination_audit


async def main() -> None:
    session_id = sys.argv[1] if len(sys.argv) > 1 else "unaq-2026_paneles_solares"
    out_path = None
    if "--json" in sys.argv:
        idx = sys.argv.index("--json")
        if idx + 1 < len(sys.argv):
            out_path = sys.argv[idx + 1]

    mem = await get_connected_memory()
    state = await mem.get_session(session_id) or {}
    report = run_forensic_contamination_audit(session_id, session_state=state)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out_path:
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(text)

    summary = report.get("summary") or {}
    blocking = int(summary.get("blocking_findings") or 0)
    passed = bool(report.get("gate_passed", blocking == 0))
    sys.exit(0 if passed else 2)


if __name__ == "__main__":
    asyncio.run(main())
