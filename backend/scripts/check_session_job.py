#!/usr/bin/env python3
import asyncio
import json
import sys

SESSION = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"


async def main():
    from app.api.deps import get_connected_memory
    from app.services.job_service import get_active_session_job

    job = get_active_session_job(SESSION)
    mem = await get_connected_memory()
    st = await mem.get_session(SESSION) or {}
    out = {
        "session_id": SESSION,
        "active_job": job,
        "current_stage": st.get("current_stage"),
        "stop_reason": st.get("stop_reason"),
    }
    tasks = [t for t in (st.get("tasks_completed") or []) if isinstance(t, dict)]
    ab = [t for t in tasks if t.get("task") == "analisis_bases"]
    out["analisis_bases_runs"] = len(ab)
    if ab:
        last = ab[-1]
        out["last_analisis"] = {
            "status": last.get("status"),
            "timestamp": last.get("completed_at") or last.get("timestamp"),
            "has_anchored_v1": bool((last.get("result") or {}).get("reglas_economicas_anchored_v1")),
        }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
