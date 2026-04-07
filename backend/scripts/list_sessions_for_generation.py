"""
Lista sesiones candidatas para prueba generation_only / simulate_profile_fill_generation.py.

Lee `state_data` (JSON) en PostgreSQL: ahí vive `tasks_completed`, no hay columnas sueltas
`name` ni `tasks_completed` en la tabla `sessions`.

Uso (desde backend/, con DATABASE_URL):

  python scripts/list_sessions_for_generation.py
"""
from __future__ import annotations

import asyncio
import os
import sys

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config.settings import settings


def _async_db_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("postgresql+asyncpg://"):
        return url
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _tasks_from_state(state_data: dict | None) -> list:
    if not state_data or not isinstance(state_data, dict):
        return []
    return state_data.get("tasks_completed") or []


async def list_sessions() -> None:
    """Imprime las últimas sesiones y los hitos útiles para generation_only."""
    print("[LicitAI] Sesiones recientes (tasks_completed dentro de state_data)...")

    conn_str = settings.DATABASE_URL or os.getenv("DATABASE_URL")
    if not conn_str:
        print("Error: DATABASE_URL no configurada.", file=sys.stderr)
        return

    engine = create_async_engine(_async_db_url(conn_str), echo=False)
    try:
        async with engine.connect() as conn:
            query = text(
                """
                SELECT id, created_at, state_data
                FROM sessions
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 20
                """
            )
            res = await conn.execute(query)

            headers = f"{'SESSION_ID':<40} | {'CREATED':<22} | {'STAGES / NOTAS':<45}"
            print("-" * len(headers))
            print(headers)
            print("-" * len(headers))

            count = 0
            for row in res:
                sid, created, state_data = row
                tasks = _tasks_from_state(state_data)
                stages = [
                    t.get("task", "").replace("stage_completed:", "")
                    for t in tasks
                    if isinstance(t, dict) and str(t.get("task", "")).startswith("stage_completed:")
                ]
                has_econ_proposal = any(
                    isinstance(t, dict) and t.get("task") == "economic_proposal" for t in tasks
                )
                has_stage_economic = any(
                    isinstance(t, dict) and t.get("task") == "stage_completed:economic" for t in tasks
                )

                stage_str = ",".join(stages) if stages else "Ninguno"
                if has_econ_proposal:
                    stage_str += " (+economic_proposal)"
                if has_stage_economic:
                    stage_str += " (+stage_economic)"

                created_s = created.isoformat()[:19] if created else "—"
                print(f"{str(sid):<40} | {created_s:<22} | {stage_str[:45]:<45}")
                count += 1

            if count == 0:
                print("No hay filas en sessions.")
            else:
                print("-" * len(headers))
                print(
                    "\nTip: para generation_only, busca analysis, compliance y economic en stage_completed; "
                    "simulate_profile_fill_generation.py avisa si falta economic_proposal."
                )
    except Exception as e:
        print(f"Error durante la inspección: {e}", file=sys.stderr)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(list_sessions())
