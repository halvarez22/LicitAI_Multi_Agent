#!/usr/bin/env python3
"""UAT HRU: curación dictamen licitante (sin hardcode por licitación)."""
from __future__ import annotations

import asyncio
import json
import re
import sys

SESSION = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"

CONVOCANTE_NOISE_PATTERNS = [
    re.compile(r"(?i)directora\s+general"),
    re.compile(r"(?i)comit[eé]\s+convocante"),
    re.compile(r"(?i)autoridad\s+responsable\s+del\s+procedimiento"),
    re.compile(r"(?i)comparece\s+con\s+personalidad"),
]


def _blob(item: dict) -> str:
    t = item.get("texto")
    if isinstance(t, dict):
        return " ".join(
            str(t.get(k) or "")
            for k in ("descripcion", "nombre", "requisito", "snippet", "texto_crudo")
        )
    return str(t or item.get("snippet") or "")


def _matches_noise(text: str) -> bool:
    return any(rx.search(text) for rx in CONVOCANTE_NOISE_PATTERNS)


async def main() -> int:
    from app.api.deps import get_connected_memory
    from app.config.settings import settings
    from app.services.dictamen_curation_service import refresh_dictamen_curation_if_needed

    mem = await get_connected_memory()
    st = await mem.get_session(SESSION) or {}
    raw_dictamen = st.get("dictamen")
    if not isinstance(raw_dictamen, dict):
        print(json.dumps({"pass": False, "reason": "no_dictamen"}, indent=2))
        return 1

    curated = refresh_dictamen_curation_if_needed(
        dict(raw_dictamen),
        session_state=st,
        extraction_health=raw_dictamen.get("extractionHealth"),
        compliance=st.get("compliance"),
        view_mode=str(settings.DICTAMEN_VIEW_MODE or "licitante"),
        curation_enabled=settings.DICTAMEN_CURATION_ENABLED,
    )

    oblig = int(curated.get("obligacionesDetectadas") or 0)
    archival = int(curated.get("archivalCount") or 0)
    legacy = int(curated.get("totalRequisitosLegacy") or len(curated.get("causalesRaw") or []))
    schema = int(curated.get("dictamen_schema_version") or 0)

    default_causales = curated.get("causales") or []
    noise_in_default = [
        _blob(c)[:120]
        for c in default_causales
        if _matches_noise(_blob(c))
    ]

    out = {
        "session_id": SESSION,
        "curation_enabled": settings.DICTAMEN_CURATION_ENABLED,
        "dictamen_schema_version": schema,
        "obligacionesDetectadas": oblig,
        "archivalCount": archival,
        "totalRequisitosLegacy": legacy,
        "reduction_pct": round(100 * (legacy - oblig) / legacy, 1) if legacy else 0,
        "noise_in_default_view": len(noise_in_default),
        "noise_samples": noise_in_default[:3],
        "uxKind": curated.get("uxKind"),
        "status": curated.get("status"),
        "PASS_schema_v3": schema >= 3,
        "PASS_has_archival_split": archival > 0 or legacy > oblig,
        "PASS_default_smaller_than_legacy": oblig < legacy if legacy else oblig >= 0,
        "PASS_no_convocante_noise_in_default": len(noise_in_default) == 0,
    }
    out["PASS_overall"] = all(
        out[k]
        for k in (
            "PASS_schema_v3",
            "PASS_default_smaller_than_legacy",
            "PASS_no_convocante_noise_in_default",
        )
    )

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["PASS_overall"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
