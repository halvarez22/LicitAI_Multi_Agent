#!/usr/bin/env python3
"""
Reporte de cobertura de entrega (plantillas convocante vs ZIP generado).

Uso:
  python scripts/coverage_report.py --session isapeg
  python scripts/coverage_report.py --session isapeg --json report.json
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


async def main() -> int:
    parser = argparse.ArgumentParser(description="Reporte de cobertura universal por sesión")
    parser.add_argument("--session", required=True, help="ID de sesión")
    parser.add_argument("--json", dest="json_path", help="Ruta de salida JSON")
    parser.add_argument("--refresh", action="store_true", help="Recalcular y persistir")
    args = parser.parse_args()

    from app.memory.factory import MemoryAdapterFactory
    from app.services.delivery_coverage_report import build_and_persist_coverage

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    try:
        if args.refresh:
            report = await build_and_persist_coverage(mem, args.session)
        else:
            st = await mem.get_session(args.session) or {}
            report = st.get("delivery_coverage_report")
            if not report:
                report = await build_and_persist_coverage(mem, args.session)
    finally:
        await mem.disconnect()

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_path:
        Path(args.json_path).write_text(text, encoding="utf-8")
        print(f"Reporte escrito en: {args.json_path}")
    else:
        print(text)

    summary = report.get("summary") or {}
    print(
        f"\nResumen: {summary.get('generadas', 0)}/{summary.get('esperadas_generar', 0)} "
        f"plantillas generadas ({summary.get('cobertura_generacion_pct', 0)}%)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
