#!/usr/bin/env python3
"""
Escaneo forense P0 de contaminación documental en entrega CompraNet (CI / smoke).

Uso:
  PYTHONPATH=. python scripts/forensic_contamination_scan.py <session_id>
  PYTHONPATH=. python scripts/forensic_contamination_scan.py <session_id> --json out.json
  PYTHONPATH=. python scripts/forensic_contamination_scan.py <session_id> --audit-only

Exit codes:
  0 — sin hallazgos bloqueantes (o enforce desactivado)
  2 — hallazgos bloqueantes P0
  3 — sin índice de entrega / sesión inválida
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.api.deps import get_connected_memory
from app.services.delivery_content_audit import (
    format_forensic_contamination_errors,
    run_forensic_contamination_audit,
)


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    session_id = args[0] if args else "unaq-2026_paneles_solares"
    out_path = None
    if "--json" in sys.argv:
        idx = sys.argv.index("--json")
        if idx + 1 < len(sys.argv):
            out_path = sys.argv[idx + 1]

    validated = Path("/data/outputs") / session_id / "_compranet_validated"
    indice = validated / "INDICE_ENTREGA.json"
    if not indice.is_file():
        print(f"Missing {indice}")
        sys.exit(3)

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
    if blocking:
        print("\n--- Bloqueantes ---", file=sys.stderr)
        for err in format_forensic_contamination_errors(report):
            print(err, file=sys.stderr)

    enforce = bool(report.get("enforce_at_pack"))
    passed = bool(report.get("gate_passed"))
    print(
        f"\nforensic_summary enforce={enforce} blocking={blocking} gate_passed={passed}",
        file=sys.stderr,
    )
    sys.exit(0 if passed else 2)


if __name__ == "__main__":
    asyncio.run(main())
