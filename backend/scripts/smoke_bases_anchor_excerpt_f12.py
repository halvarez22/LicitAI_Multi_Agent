#!/usr/bin/env python3
"""Smoke F12.2 — show paragraph intent + safe price_source label."""

from __future__ import annotations

import sys

from app.agents.chatbot_rag import ChatbotRAGAgent
from app.services.bases_anchor_excerpt_service import detect_show_paragraph_intent, resolve_active_claim_anchor
from app.services.evidence_anchor_service import normalize_evidence_anchor


def main() -> int:
    errors: list[str] = []
    if not detect_show_paragraph_intent("muéstrame el párrafo"):
        errors.append("intent")
    pending = [
        {
            "type": "economic_validation_blocking",
            "field": "economic_price_source",
            "input_mode": "price_source",
            "blocking_items": [
                {
                    "concepto_label": "Integración",
                    "page_number": 27,
                    "context_snippet": "Integración del precio unitario mensual y diario sin IVA por operario",
                    "source_name": "BASES.pdf",
                }
            ],
        }
    ]
    anchor = resolve_active_claim_anchor({}, pending, 0)
    if anchor.get("page") != 27:
        errors.append("anchor_page")
    syn = normalize_evidence_anchor(
        {"page": 1, "snippet": "Cotización en chat — X", "is_synthetic": True},
        force_synthetic=True,
    )
    if syn.get("anchor_quality") != "synthetic":
        errors.append("synthetic")
    hint = ChatbotRAGAgent._price_source_concept_hint_from_query(
        "precio diario 560 y mensual 16800", {}
    )
    if "diario" not in hint.lower() and "mensual" not in hint.lower() and "precio" not in hint.lower():
        errors.append("hint")
    if errors:
        print("SMOKE F12.2 FAIL:", ", ".join(errors))
        return 1
    print("SMOKE F12.2 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
