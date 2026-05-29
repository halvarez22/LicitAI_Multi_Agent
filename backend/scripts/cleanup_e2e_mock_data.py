#!/usr/bin/env python3
"""
Elimina sesiones/empresas y carpetas de salida creadas por E2E mock (e2e_*, co_e2e_*, sess_patch).
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

OUTPUTS = Path("/data/outputs")
INPUTS = Path("/data/inputs")

SESSION_PREFIXES = ("e2e_", "e2e-", "sess_patch")
COMPANY_PREFIXES = ("co_e2e_", "co_mock")


def _matches_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    low = (name or "").lower()
    return any(low.startswith(p.lower()) for p in prefixes)


def _cleanup_disk(dry_run: bool) -> dict:
    removed_dirs: list[str] = []
    for base in (OUTPUTS, INPUTS):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and _matches_prefix(child.name, SESSION_PREFIXES):
                removed_dirs.append(str(child))
                if not dry_run:
                    shutil.rmtree(child, ignore_errors=True)
    return {"dirs_removed": removed_dirs}


async def _cleanup_db(dry_run: bool) -> dict:
    from sqlalchemy import delete, select

    from app.memory.factory import MemoryAdapterFactory
    from app.models.company import Company
    from app.models.session import Session

    memory = MemoryAdapterFactory.create_adapter()
    if memory is None or not await memory.connect():
        return {"db": "unavailable"}

    removed_sessions: list[str] = []
    removed_companies: list[str] = []

    try:
        all_sessions = await memory.list_sessions()
        for row in all_sessions or []:
            sid = str(row.get("id") or "")
            if _matches_prefix(sid, SESSION_PREFIXES):
                removed_sessions.append(sid)
                if not dry_run:
                    await memory.delete_session(sid)

        factory = getattr(memory, "async_session", None)
        if factory and not dry_run:
            async with factory() as db:
                res = await db.execute(select(Company.id))
                for (cid,) in res.fetchall():
                    if _matches_prefix(str(cid), COMPANY_PREFIXES):
                        removed_companies.append(str(cid))
                if removed_companies:
                    await db.execute(
                        delete(Company).where(Company.id.in_(removed_companies))
                    )
                    await db.commit()
        elif factory and dry_run:
            async with factory() as db:
                res = await db.execute(select(Company.id))
                removed_companies = [
                    str(cid)
                    for (cid,) in res.fetchall()
                    if _matches_prefix(str(cid), COMPANY_PREFIXES)
                ]
    except Exception as exc:
        return {"db_error": str(exc)}
    finally:
        await memory.disconnect()

    return {
        "sessions_removed": removed_sessions,
        "companies_removed": removed_companies,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    disk = _cleanup_disk(args.dry_run)
    db = await _cleanup_db(args.dry_run)
    print({"disk": disk, "db": db})
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
