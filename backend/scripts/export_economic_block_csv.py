#!/usr/bin/env python3
"""Exporta a CSV el bloque económico activo de una sesión."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.memory.factory import MemoryAdapterFactory
from app.services.interaction_block_csv_io import (
    write_interaction_block_csv,
    write_interaction_block_metadata,
)
from app.services.requirement_grouper import build_interaction_block


async def _run(session_id: str, company_id: str, out_path: Path) -> int:
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
            raise RuntimeError("No hay bloque económico agrupable activo para exportar.")
        csv_path = write_interaction_block_csv(block, out_path)
        meta_path = write_interaction_block_metadata(
            block,
            out_path.with_suffix(".meta.json"),
            session_id=session_id,
            company_id=company_id,
            extra={"csv_path": str(csv_path)},
        )
        print(
            json.dumps(
                {
                    "success": True,
                    "session_id": session_id,
                    "company_id": company_id,
                    "block_id": block.block_id,
                    "items": len(block.items),
                    "csv_path": str(csv_path),
                    "metadata_path": str(meta_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        await memory.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta a CSV el bloque económico activo.")
    parser.add_argument("--session-id", required=True, help="ID de sesión.")
    parser.add_argument("--company-id", required=True, help="ID de empresa.")
    parser.add_argument("--out", required=True, help="Ruta del CSV de salida.")
    args = parser.parse_args()
    return asyncio.run(_run(args.session_id, args.company_id, Path(args.out)))


if __name__ == "__main__":
    raise SystemExit(main())
