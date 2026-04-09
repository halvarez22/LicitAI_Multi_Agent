from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _to_async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _extract_stage_result(tasks: list[dict[str, Any]], task_name: str) -> Optional[Dict[str, Any]]:
    for task in reversed(tasks):
        if isinstance(task, dict) and task.get("task") == task_name:
            result = task.get("result")
            return result if isinstance(result, dict) else None
    return None


async def export_inputs(session_id: str, database_url: str, out_dir: Path) -> int:
    engine = create_async_engine(_to_async_url(database_url), echo=False)
    try:
        async with engine.connect() as conn:
            query = text("SELECT state_data FROM sessions WHERE id = :sid")
            res = await conn.execute(query, {"sid": session_id})
            row = res.first()
            if not row:
                print(f"No existe la sesión: {session_id}")
                return 2
            state_data = row[0] if isinstance(row[0], dict) else {}
            tasks = state_data.get("tasks_completed", []) if isinstance(state_data, dict) else []
            if not isinstance(tasks, list):
                tasks = []

            analysis = _extract_stage_result(tasks, "stage_completed:analysis")
            compliance = _extract_stage_result(tasks, "stage_completed:compliance")
            economic = _extract_stage_result(tasks, "stage_completed:economic")
            compranet_pack = _extract_stage_result(tasks, "stage_completed:compranet_pack")

            missing = []
            if analysis is None:
                missing.append("analysis")
            if compliance is None:
                missing.append("compliance")
            if economic is None:
                missing.append("economic")
            if missing:
                print(f"Faltan stages para oracle en sesión {session_id}: {', '.join(missing)}")
                return 3

            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
            (out_dir / "compliance.json").write_text(json.dumps(compliance, ensure_ascii=False, indent=2), encoding="utf-8")
            (out_dir / "economic.json").write_text(json.dumps(economic, ensure_ascii=False, indent=2), encoding="utf-8")
            if compranet_pack is not None:
                (out_dir / "packager.json").write_text(
                    json.dumps(compranet_pack, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(f"Exportados inputs oracle en: {out_dir}")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta analysis/compliance/economic desde tasks_completed.")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--database-url", default="postgresql://postgres:postgres@localhost:5432/licitaciones")
    parser.add_argument("--out", default="out/oracle_real")
    args = parser.parse_args()

    import asyncio

    return asyncio.run(
        export_inputs(
            session_id=args.session_id,
            database_url=args.database_url,
            out_dir=Path(args.out),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
