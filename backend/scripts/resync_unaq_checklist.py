"""Re-sincroniza checklist de hitos desde corpus (smoke post-fix fallo)."""
from __future__ import annotations

import asyncio

from app.api.deps import get_connected_memory
from app.checklist.submission_checklist_service import ensure_session_cronograma_and_checklist


async def main() -> None:
    sid = "unaq-2026_paneles_solares"
    mem = await get_connected_memory()
    model = await ensure_session_cronograma_and_checklist(mem, sid)
    if not model:
        print("sin checklist")
        return
    for h in model.hitos:
        print(h.id, h.fecha_texto_raw, h.fecha_hora)


if __name__ == "__main__":
    asyncio.run(main())
