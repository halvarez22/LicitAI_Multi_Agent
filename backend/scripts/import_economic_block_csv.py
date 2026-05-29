#!/usr/bin/env python3
"""Importa a la sesión un CSV capturado para el bloque económico activo."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.memory.factory import MemoryAdapterFactory
from app.services.interaction_block_csv_io import read_mass_save_rows
from app.services.interaction_block_mass_save import mass_save_economic_block
from app.services.requirement_grouper import build_interaction_block


async def _run(session_id: str, company_id: str, csv_path: Path, correlation_id: str) -> int:
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()
    try:
        session_state = await memory.get_session(session_id)
        if session_state is None:
            raise RuntimeError(f"Sesión no encontrada: {session_id}")
        company = await memory.get_company(company_id) or {}
        catalog = company.get("catalog") if isinstance(company.get("catalog"), list) else []
        current_idx = int(session_state.get("current_question_index") or 0)
        block = build_interaction_block(
            session_id=session_id,
            session_state=session_state,
            company_catalog=catalog,
            current_idx=current_idx,
        )
        if block is None:
            raise RuntimeError("No hay bloque económico agrupable activo para importar.")
        rows = read_mass_save_rows(csv_path)
        if not rows:
            raise RuntimeError("El CSV no contiene filas con item_id y value.")
        result = await mass_save_economic_block(
            memory,
            session_id=session_id,
            company_id=company_id,
            block_id=block.block_id,
            correlation_id=correlation_id,
            rows=rows,
        )
        print(
            json.dumps(
                {
                    "success": result.get("success_count", 0) > 0,
                    "session_id": session_id,
                    "company_id": company_id,
                    "block_id": block.block_id,
                    "rows_read": len(rows),
                    **result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result.get("success_count", 0) > 0 else 2
    finally:
        await memory.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa un CSV al bloque económico activo.")
    parser.add_argument("--session-id", required=True, help="ID de sesión.")
    parser.add_argument("--company-id", required=True, help="ID de empresa.")
    parser.add_argument("--csv", required=True, help="Ruta del CSV ya capturado.")
    parser.add_argument(
        "--correlation-id",
        default=f"csv-import-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        help="ID de correlación para auditoría.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.session_id, args.company_id, Path(args.csv), args.correlation_id))


if __name__ == "__main__":
    raise SystemExit(main())
