#!/usr/bin/env python3
"""UAT BARDA: ¿pasa el gate forense post-fix HRU?"""
from __future__ import annotations

import asyncio
import json
import sys

SESSION = sys.argv[1] if len(sys.argv) > 1 else "barda_primaria_lopez_rayon"
PHANTOM = "El presupuesto debe ser de $1,000,000.00 o más"


async def main() -> int:
    from app.api.deps import get_connected_memory
    from app.services.reglas_economicas_evidence_service import (
        build_forensic_alerts_from_evidence_block,
        build_reglas_economicas_evidence_v1,
    )
    from app.services.economic_alert_classifier import normalize_and_dedupe_economic_alerts
    from app.services.forensic_risk_service import attach_forensic_risks_to_dictamen

    mem = await get_connected_memory()
    st = await mem.get_session(SESSION) or {}
    if not st:
        print(json.dumps({"pass": False, "reason": "session_not_found"}, indent=2))
        return 1

    # Reglas del analista (tasks_completed)
    raw_reglas = {}
    for t in st.get("tasks_completed") or []:
        if isinstance(t, dict) and t.get("task") == "analisis_bases":
            raw_reglas = (t.get("result") or {}).get("reglas_economicas") or {}
            stored_ev = (t.get("result") or {}).get("reglas_economicas_evidence_v1")
            break
    else:
        stored_ev = None

    # Simular build evidence (siempre fresco con motor actual)
    evidence_block = await build_reglas_economicas_evidence_v1(
        SESSION, raw_reglas, memory=mem, session_state=st
    )
    forensic_alerts = build_forensic_alerts_from_evidence_block(evidence_block)

    phantom_in_forensic_alerts = any(
        PHANTOM in str(a.get("texto") or "") for a in forensic_alerts
    )

    # Dictamen actual + sanitize
    dictamen = st.get("dictamen") or {}
    dictamen_out = attach_forensic_risks_to_dictamen(dict(dictamen))
    panel_items = (dictamen_out.get("forensic_risks_v1") or {}).get("items") or []
    phantom_in_panel = any(
        PHANTOM in str(
            (it.get("texto") if isinstance(it.get("texto"), str) else "")
            or it.get("_literal")
            or ""
        )
        for it in panel_items
    )

    # Gate classifier sobre texto fantasma
    forensic_norm, _ = normalize_and_dedupe_economic_alerts([PHANTOM])
    phantom_passes_classifier = len(forensic_norm) > 0

    checks = {
        "session_id": SESSION,
        "evidence_stats": evidence_block.get("stats"),
        "phantom_rule_promotion_eligible": (
            (evidence_block.get("items") or {})
            .get("referencia_partidas_anexos_citados", {})
            .get("promotion_eligible")
        ),
        "forensic_alerts_count": len(forensic_alerts),
        "phantom_in_forensic_alerts": phantom_in_forensic_alerts,
        "panel_forensic_items_count": len(panel_items),
        "phantom_in_panel_after_sanitize": phantom_in_panel,
        "phantom_passes_classifier_gate": phantom_passes_classifier,
        "stored_evidence_v1_in_analisis_bases": stored_ev is not None,
    }

    passed = (
        not phantom_in_forensic_alerts
        and not phantom_passes_classifier
        and checks["phantom_rule_promotion_eligible"] is False
        and evidence_block.get("stats", {}).get("promotion_eligible", 1) == 0
    )
    # Panel puede tener fantasma si dictamen viejo no re-corrió; gate nuevo debe bloquearlo al re-armar
    panel_ok = not phantom_in_panel

    checks["PASS_gate_engine"] = passed
    checks["PASS_panel_current_dictamen"] = panel_ok
    checks["PASS_overall"] = passed and panel_ok

    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["PASS_overall"] else 2 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
