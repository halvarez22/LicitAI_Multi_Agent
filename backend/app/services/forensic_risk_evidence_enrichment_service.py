"""
Hidratación HRU de evidencia forense para ítems de riesgo (panel + dictamen).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.logging_config import get_logger
from app.services.economic_risk_evidence_v1 import build_evidence_v1, merge_evidence_into_item

logger = get_logger(__name__)


def _literal_from_item(item: Dict[str, Any]) -> str:
    texto = item.get("texto")
    if isinstance(texto, dict):
        return str(texto.get("descripcion") or texto.get("nombre") or "").strip()
    return str(texto or item.get("_literal") or "").strip()


async def hydrate_forensic_risk_item_evidence(
    session_id: str,
    item: Dict[str, Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
    memory: Any = None,
) -> Dict[str, Any]:
    """Resuelve evidencia indexada para un ítem de riesgo."""
    literal = _literal_from_item(item)
    if not literal or not session_id:
        return item

    risk_ctx = {
        "page": item.get("page"),
        "snippet": item.get("snippet"),
        "source": item.get("source"),
        "alert_subtype": item.get("alert_subtype"),
        "risk_id": item.get("risk_id"),
    }
    error_type: Optional[str] = None
    raw_ev: Dict[str, Any] = {}
    try:
        from app.services.forensic_risk_evidence_service import resolve_forensic_risk_evidence

        raw_ev = await resolve_forensic_risk_evidence(
            session_id,
            literal,
            risk_ctx=risk_ctx,
            session_state=session_state,
            memory=memory,
        )
    except Exception as exc:
        error_type = "FORENSIC_EVIDENCE_INDEX_ERROR"
        logger.warning(
            "forensic_evidence_hydrate_failed session=%s risk_id=%s err=%s",
            session_id,
            item.get("risk_id"),
            exc,
        )

    evidence_v1 = build_evidence_v1(raw_ev, literal=literal, error_type=error_type)
    enriched = merge_evidence_into_item(item, evidence_v1)
    enriched["evidence_v1"] = evidence_v1

    # Re-sincronizar subtipo y UX desde policy con snippet real
    try:
        from app.services.economic_alert_classifier import (
            disambiguate_subtype_with_evidence,
            classify_economic_alert_text,
            ux_reason_for_subtype,
        )

        base = classify_economic_alert_text(literal)
        subtype = disambiguate_subtype_with_evidence(
            base,
            literal,
            str(evidence_v1.get("snippet") or "") or None,
        )
        enriched["alert_subtype"] = subtype
        enriched["risk_reason_ux"] = ux_reason_for_subtype(subtype)
    except Exception:
        pass

    return enriched


async def hydrate_forensic_risks_block(
    session_id: str,
    forensic_risks: Dict[str, Any],
    *,
    session_state: Optional[Dict[str, Any]] = None,
    memory: Any = None,
) -> Dict[str, Any]:
    """Hidrata evidencia v1 en todos los ítems del bloque forensic_risks_v1."""
    items_out: List[Dict[str, Any]] = []
    for item in forensic_risks.get("items") or []:
        if not isinstance(item, dict):
            continue
        items_out.append(
            await hydrate_forensic_risk_item_evidence(
                session_id,
                item,
                session_state=session_state,
                memory=memory,
            )
        )
    return {**forensic_risks, "items": items_out, "evidence_hydrated": True}
