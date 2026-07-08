#!/usr/bin/env python3
"""Verifica reglas_economicas_anchored_v1 tras re-análisis de bases."""
from __future__ import annotations

import asyncio
import json
import sys

SESSION = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"


async def main() -> int:
    from app.api.deps import get_connected_memory

    mem = await get_connected_memory()
    st = await mem.get_session(SESSION) or {}
    result = None
    for t in st.get("tasks_completed") or []:
        if isinstance(t, dict) and t.get("task") == "analisis_bases":
            result = t.get("result") or {}
            break

    if not result:
        print(json.dumps({"pass": False, "reason": "no_analisis_bases"}, indent=2))
        return 1

    anchored = result.get("reglas_economicas_anchored_v1")
    evidence = result.get("reglas_economicas_evidence_v1")
    reglas = result.get("reglas_economicas")

    ev_stats = (evidence or {}).get("stats") if isinstance(evidence, dict) else {}
    anchor_count = len(anchored or {}) if isinstance(anchored, dict) else 0
    analyst_anchors = int(ev_stats.get("analyst_anchors_provided") or 0)
    index_verified = int(ev_stats.get("index_verified") or 0)

    sample = {}
    if isinstance(anchored, dict):
        for k, v in list(anchored.items())[:2]:
            sample[k] = v

    out = {
        "session_id": SESSION,
        "has_anchored_v1": anchored is not None,
        "anchored_keys": anchor_count,
        "evidence_stats": ev_stats,
        "analyst_anchors_provided": analyst_anchors,
        "index_verified": index_verified,
        "reglas_flat_keys_with_value": sum(
            1
            for v in (reglas or {}).values()
            if isinstance(v, str) and v.strip() and v != "No especificado"
        ),
        "sample_anchored": sample,
        "PASS_has_evidence_block": bool(evidence),
        "PASS_anchored_or_legacy": anchor_count > 0 or bool(ev_stats.get("total")),
    }
    out["PASS_overall"] = out["PASS_has_evidence_block"] and out["PASS_anchored_or_legacy"]

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["PASS_overall"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
