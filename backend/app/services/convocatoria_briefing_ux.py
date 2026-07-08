"""
Render UX HRU del briefing de convocatoria — lenguaje llano centralizado.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.chat_gate5_formatter import format_gate5_briefing_opening

_CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
_UX_PATH = _CONTRACTS_DIR / "convocatoria_briefing_ux_messages.json"


@lru_cache(maxsize=1)
def load_convocatoria_briefing_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def ux_messages_version() -> str:
    return str(load_convocatoria_briefing_ux_messages().get("messages_version") or "")


def humanize_plain_label(raw: str) -> str:
    """Aplica glosario HRU a etiquetas visibles al usuario."""
    text = str(raw or "").strip()
    if not text:
        return text
    msgs = load_convocatoria_briefing_ux_messages()
    for rule in msgs.get("humanize_lexicon") or []:
        if not isinstance(rule, dict):
            continue
        pat = str(rule.get("pattern") or "")
        repl = str(rule.get("replacement") or "")
        if pat:
            text = re.sub(pat, repl, text)
    return text


def _block_by_id(briefing: Dict[str, Any], block_id: str) -> Dict[str, Any]:
    for block in briefing.get("blocks") or []:
        if isinstance(block, dict) and str(block.get("block_id") or "") == block_id:
            return block
    return {}


def render_opening_message(
    *,
    session_state: Dict[str, Any],
    briefing: Dict[str, Any],
) -> str:
    """
    Compone mensaje de apertura Gate 5 (modo briefing, hasta 4 líneas).
    """
    msgs = load_convocatoria_briefing_ux_messages()
    opening = msgs.get("opening") if isinstance(msgs.get("opening"), dict) else {}
    session_name = str(session_state.get("name") or "esta licitación").strip() or "esta licitación"

    admin = _block_by_id(briefing, "administrative")
    tech = _block_by_id(briefing, "technical")
    eco = _block_by_id(briefing, "economic")
    total_items = int(admin.get("item_count") or 0) + int(tech.get("item_count") or 0) + int(eco.get("item_count") or 0)

    if total_items >= 2:
        blocks_line = str(opening.get("blocks_compact") or "").format(
            admin_title=admin.get("title_plain", "Documentos"),
            admin_count=int(admin.get("item_count") or 0),
            tech_title=tech.get("title_plain", "Técnica"),
            tech_count=int(tech.get("item_count") or 0),
            eco_title=eco.get("title_plain", "Cotización"),
            eco_count=int(eco.get("item_count") or 0),
        )
    else:
        blocks_line = str(opening.get("blocks_compact_sparse") or "")

    track = str(briefing.get("recommended_first_track") or "economic")
    action = briefing.get("recommended_first_action") if isinstance(briefing.get("recommended_first_action"), dict) else {}
    action_label = humanize_plain_label(str(action.get("label_plain") or "el siguiente dato"))

    from app.services.evidence_anchor_service import (
        claim_quality_for_ux,
        format_claim_locus,
        evidence_anchor_enabled,
    )
    from app.services.evidence_anchor_service import load_pliego_pedagogico_ux_messages

    anchor = action.get("evidence_anchor") if isinstance(action.get("evidence_anchor"), dict) else {}
    locus = format_claim_locus(anchor) if evidence_anchor_enabled() else ""
    pedagogia = load_pliego_pedagogico_ux_messages() if evidence_anchor_enabled() else {}
    quality = claim_quality_for_ux(anchor)

    if track == "economic" and str(action.get("input_mode") or "") == "price_source":
        if locus and pedagogia.get("first_action_price_source_with_page"):
            first_line = str(pedagogia.get("first_action_price_source_with_page")).format(
                action_label=action_label,
                locus=locus,
            )
        else:
            first_line = str(opening.get("first_action_economic_price_source") or "").format(action_label=action_label)
        cta = str(opening.get("cta_economic") or "")
    elif track == "economic":
        if locus and pedagogia.get("first_action_with_page"):
            first_line = str(pedagogia.get("first_action_with_page")).format(
                action_label=action_label,
                locus=locus,
            )
        else:
            first_line = str(opening.get("first_action_economic") or "").format(action_label=action_label)
        cta = str(opening.get("cta_economic") or "")
    elif track == "technical":
        first_line = str(opening.get("first_action_technical") or "").format(action_label=action_label)
        if locus:
            first_line = f"{first_line} {locus}".strip()
        cta = str(opening.get("cta_technical") or "")
    else:
        first_line = str(opening.get("first_action_administrative") or "").format(action_label=action_label)
        if locus:
            first_line = f"{first_line} {locus}".strip()
        cta = str(opening.get("cta_administrative") or "")

    if quality == "verified" and pedagogia.get("cta_show_paragraph"):
        # F12.1: CTA sugiere párrafo; F12.2 cableará el handler completo.
        cta = f"{cta} {pedagogia.get('cta_show_paragraph')}".strip()

    reason = str(briefing.get("recommended_first_track_reason_plain") or "").strip()
    reason_suffix = str(opening.get("reason_suffix") or "{reason_plain}").format(reason_plain=reason)
    detail = f"{blocks_line} {first_line}"
    if reason and len(detail) < 360:
        detail = f"{detail} {reason_suffix}"

    status = str(opening.get("status") or "").format(session_name=session_name)
    return format_gate5_briefing_opening(status=status, detail=detail, cta=cta)


def render_panel_briefing_summary(briefing: Dict[str, Any]) -> Dict[str, Any]:
    """Payload compacto para card en DeliveryPanel."""
    msgs = load_convocatoria_briefing_ux_messages()
    panel = msgs.get("panel") if isinstance(msgs.get("panel"), dict) else {}
    confidence = str((briefing.get("quality_signals") or {}).get("confidence") or "media")
    blocks_out: List[Dict[str, Any]] = []
    for block in briefing.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        blocks_out.append(
            {
                "block_id": block.get("block_id"),
                "title": block.get("title_plain"),
                "summary": block.get("summary_plain"),
                "examples": list(block.get("example_items") or [])[:3],
                "item_count": block.get("item_count"),
                "provenance_ui": block.get("provenance_ui"),
                "page_refs": (block.get("provenance_ui") or {}).get("page_refs")
                if isinstance(block.get("provenance_ui"), dict)
                else [],
            }
        )
    note = ""
    if confidence == "baja":
        note = str(panel.get("confidence_baja") or "")
    first_action = briefing.get("recommended_first_action") if isinstance(
        briefing.get("recommended_first_action"), dict
    ) else {}
    return {
        "card_title": str(panel.get("card_title") or "Qué pide la convocante"),
        "tender_object": briefing.get("tender_object_plain"),
        "blocks": blocks_out,
        "recommended_first_track": briefing.get("recommended_first_track"),
        "recommended_first_action": {
            "label_plain": first_action.get("label_plain"),
            "evidence_anchor": first_action.get("evidence_anchor"),
            "provenance_ui": first_action.get("provenance_ui"),
        },
        "confidence": confidence,
        "note": note,
    }
