#!/usr/bin/env python3
"""Smoke F12.1 — evidence_anchor fail-closed + briefing first_action."""

from __future__ import annotations

import sys

from app.agents.economic import _ensure_chat_anchor
from app.services.convocatoria_briefing_service import build_convocatoria_briefing_canonical_v1
from app.services.evidence_anchor_service import (
    is_claim_locus_visible,
    normalize_evidence_anchor,
    policy_version,
)


def main() -> int:
    errors: list[str] = []
    if not policy_version().startswith("evidence-anchor-v1"):
        errors.append("policy_version")

    syn = normalize_evidence_anchor(_ensure_chat_anchor({}, "Zona A"), force_synthetic=True)
    if syn.get("anchor_quality") != "synthetic" or is_claim_locus_visible(syn):
        errors.append("synthetic_visible")

    verified = normalize_evidence_anchor(
        {
            "source_name": "BASES.pdf",
            "page": 27,
            "snippet": "Integración del precio unitario mensual y diario sin IVA por operario",
        }
    )
    if verified.get("anchor_quality") != "verified":
        errors.append("verified_quality")

    state = {
        "name": "Smoke vigilancia",
        "tasks_completed": [{"task": "stage_completed:analysis"}],
        "session_line_items": [{"concepto_raw": "Zona A", "extra": {"location_label": "Zona A"}}],
        "economic_user_inputs": {},
        "compliance_master_list": {
            "economico": [
                {
                    "nombre": "Integración precio",
                    "page": 27,
                    "snippet": "Integración del precio unitario mensual sin IVA",
                    "archivo_fuente": "BASES.pdf",
                }
            ]
        },
    }
    briefing = build_convocatoria_briefing_canonical_v1(state)
    action = briefing.get("recommended_first_action") or {}
    if "evidence_anchor" not in action:
        errors.append("first_action_missing_anchor")
    elif not isinstance(action.get("evidence_anchor"), dict):
        errors.append("first_action_anchor_type")

    if errors:
        print("SMOKE F12.1 FAIL:", ", ".join(errors))
        return 1
    print(
        "SMOKE F12.1 OK — quality=",
        (action.get("evidence_anchor") or {}).get("anchor_quality"),
        "page=",
        (action.get("evidence_anchor") or {}).get("page"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
