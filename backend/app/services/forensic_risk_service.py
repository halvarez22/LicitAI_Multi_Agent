"""
Evaluación de riesgos forenses del dictamen — enriquecimiento UX + HITL auditable.

HRU: reglas universales por categoría de riesgo, sin hardcode por licitación.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

RiskKind = Literal["knockout_causal", "economic_alert", "economic_context"]
RiskSeverity = Literal["blocking", "high", "medium"]
DecisionStatus = Literal["accepted", "rejected", "pending"]

RISK_REASON_BY_CATEGORY: Dict[str, str] = {
    "risk": (
        "Las bases prevén esta condición como causa de desechamiento o incumplimiento grave. "
        "Si no la cubres documentalmente, puedes quedar fuera del procedimiento."
    ),
    "economic": (
        "El agente económico detectó una alerta sobre precios, coherencia de oferta o riesgo "
        "financiero en tu propuesta respecto a las bases."
    ),
    "economic_gap_context": (
        "Falta contexto en bases o expediente para cotizar con seguridad (partidas, reglas o "
        "insumos económicos incompletos). Conviene resolverlo antes de ofertar."
    ),
}

RISK_GROUP_LABELS: Dict[str, str] = {
    "knockout_causal": "Descalificación / desechamiento",
    "economic_alert": "Riesgo económico",
    "economic_context": "Contexto económico pendiente",
}


def _hallazgo_text(h: Dict[str, Any]) -> str:
    texto = h.get("texto")
    if isinstance(texto, dict):
        for key in ("descripcion", "nombre", "requisito", "snippet", "texto_crudo"):
            val = texto.get(key)
            if val:
                return str(val).strip()
        return str(texto)
    return str(texto or "").strip()


def classify_risk_kind(h: Dict[str, Any]) -> RiskKind:
    cat = str(h.get("category") or "").lower()
    if cat == "risk":
        return "knockout_causal"
    if cat == "economic_gap_context":
        return "economic_context"
    return "economic_alert"


def classify_risk_severity(kind: RiskKind) -> RiskSeverity:
    if kind == "knockout_causal":
        return "blocking"
    if kind == "economic_alert":
        return "high"
    return "medium"


def risk_reason_ux(h: Dict[str, Any]) -> str:
    cat = str(h.get("category") or "").lower()
    return RISK_REASON_BY_CATEGORY.get(
        cat,
        "Hallazgo marcado como riesgo por los agentes de auditoría. Revisa el texto literal y la página citada.",
    )


def stable_risk_id(h: Dict[str, Any], index: int) -> str:
    rid = h.get("id") or h.get("entityRef")
    if rid and str(rid).strip():
        return str(rid).strip()
    return f"forensic-risk-{index}"


def enrich_risk_hallazgo(h: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """Añade metadatos de riesgo forense a un hallazgo con isRisk."""
    kind = classify_risk_kind(h)
    cat = str(h.get("category") or "").lower()
    texto_raw = h.get("texto")
    literal = (
        str(texto_raw)
        if not isinstance(texto_raw, dict)
        else str(texto_raw.get("descripcion") or texto_raw.get("nombre") or "")
    )
    subtype = str(h.get("alert_subtype") or "").strip()
    snippet_for_disambig = h.get("snippet")
    if cat in ("economic", "economic_gap_context", "economic_context"):
        try:
            from app.services.economic_alert_classifier import (
                classify_economic_alert_text,
                disambiguate_subtype_with_evidence,
            )

            base = classify_economic_alert_text(literal) if literal else "generic_economic"
            if not subtype:
                subtype = disambiguate_subtype_with_evidence(
                    base,
                    literal,
                    str(snippet_for_disambig) if snippet_for_disambig else None,
                )
            elif snippet_for_disambig:
                subtype = disambiguate_subtype_with_evidence(
                    subtype,
                    literal,
                    str(snippet_for_disambig),
                )
        except Exception:
            if not subtype:
                subtype = ""
    if subtype and cat in ("economic", "economic_gap_context", "economic_context"):
        try:
            from app.services.economic_alert_classifier import risk_severity_for_subtype

            severity: RiskSeverity = risk_severity_for_subtype(subtype)  # type: ignore[assignment]
        except Exception:
            severity = classify_risk_severity(kind)
    else:
        severity = classify_risk_severity(kind)
    try:
        from app.services.economic_alert_classifier import ux_reason_for_subtype

        reason = ux_reason_for_subtype(subtype) if subtype else ""
    except Exception:
        reason = ""
    if not reason:
        reason = str(h.get("risk_reason_ux") or "").strip()
    if not reason:
        reason = risk_reason_ux(h)
    rid = stable_risk_id(h, index)
    return {
        **h,
        "risk_id": rid,
        "risk_kind": kind,
        "risk_severity": severity,
        "alert_subtype": subtype or None,
        "risk_group_label": RISK_GROUP_LABELS.get(kind, "Riesgo forense"),
        "risk_reason_ux": reason,
        "provenance_ui": {
            "agent_id": h.get("agent_id"),
            "category": h.get("category"),
            "alert_subtype": subtype or None,
            "page": h.get("page"),
            "snippet": h.get("snippet"),
            "tipo": h.get("tipo"),
        },
    }


def build_forensic_risks_v1(causales: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Construye bloque forensic_risks_v1 desde causales accionables."""
    items: List[Dict[str, Any]] = []
    for i, h in enumerate(causales or []):
        if not isinstance(h, dict) or not h.get("isRisk"):
            continue
        items.append(enrich_risk_hallazgo(h, i))
    stats = {
        "total": len(items),
        "blocking": sum(1 for x in items if x.get("risk_severity") == "blocking"),
        "high": sum(1 for x in items if x.get("risk_severity") == "high"),
        "medium": sum(1 for x in items if x.get("risk_severity") == "medium"),
        "by_kind": {
            k: sum(1 for x in items if x.get("risk_kind") == k)
            for k in ("knockout_causal", "economic_alert", "economic_context")
        },
    }
    return {
        "schema_version": "forensic_risks_v1",
        "items": items,
        "stats": stats,
    }


def attach_forensic_risks_to_dictamen(dictamen: Dict[str, Any]) -> Dict[str, Any]:
    """Enriquece dictamen persistido con forensic_risks_v1."""
    causales = list(dictamen.get("causales") or [])
    try:
        from app.services.economic_alert_classifier import sanitize_economic_causales

        causales = sanitize_economic_causales(causales)
    except Exception:
        pass
    block = build_forensic_risks_v1(causales)
    return {
        **dictamen,
        "causales": causales,
        "forensic_risks_v1": block,
        "riesgos": block["stats"]["total"],
    }


async def attach_and_hydrate_forensic_risks(
    dictamen: Dict[str, Any],
    session_id: str,
    *,
    session_state: Optional[Dict[str, Any]] = None,
    memory: Any = None,
) -> Dict[str, Any]:
    """Adjunta riesgos forenses e hidrata evidencia indexada (HRU)."""
    out = attach_forensic_risks_to_dictamen(dictamen)
    block = out.get("forensic_risks_v1") or {}
    if session_id and block.get("items"):
        from app.services.forensic_risk_evidence_enrichment_service import hydrate_forensic_risks_block

        hydrated = await hydrate_forensic_risks_block(
            session_id,
            block,
            session_state=session_state,
            memory=memory,
        )
        out["forensic_risks_v1"] = hydrated
    return out


def _default_decisions_record() -> Dict[str, Any]:
    return {
        "schema_version": "risk_decisions_v1",
        "decisions": {},
        "batch": None,
    }


def normalize_risk_decisions(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _default_decisions_record()
    decisions = raw.get("decisions")
    if isinstance(decisions, list):
        mapped = {
            str(d.get("risk_id")): d
            for d in decisions
            if isinstance(d, dict) and d.get("risk_id")
        }
    elif isinstance(decisions, dict):
        mapped = dict(decisions)
    else:
        mapped = {}
    return {
        "schema_version": "risk_decisions_v1",
        "decisions": mapped,
        "batch": raw.get("batch"),
    }


def merge_risk_decisions_into_items(
    forensic_risks: Dict[str, Any],
    risk_decisions: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Fusiona estado HITL del usuario en ítems de riesgo para la UI."""
    decisions = normalize_risk_decisions(risk_decisions).get("decisions") or {}
    items = []
    for item in forensic_risks.get("items") or []:
        rid = item.get("risk_id")
        dec = decisions.get(rid) if rid else None
        status = "pending"
        user_note = None
        decided_at = None
        if isinstance(dec, dict):
            status = str(dec.get("status") or "pending")
            user_note = dec.get("user_note")
            decided_at = dec.get("decided_at")
        items.append({**item, "decision_status": status, "user_note": user_note, "decided_at": decided_at})
    pending = sum(1 for x in items if x.get("decision_status") == "pending")
    accepted = sum(1 for x in items if x.get("decision_status") == "accepted")
    rejected = sum(1 for x in items if x.get("decision_status") == "rejected")
    blocking_pending = sum(
        1
        for x in items
        if x.get("risk_severity") == "blocking" and x.get("decision_status") == "pending"
    )
    return {
        **forensic_risks,
        "items": items,
        "decision_stats": {
            "pending": pending,
            "accepted": accepted,
            "rejected": rejected,
            "blocking_pending": blocking_pending,
        },
    }


def apply_risk_decision_updates(
    existing: Any,
    *,
    decision_updates: Optional[List[Dict[str, Any]]] = None,
    batch_action: Optional[str] = None,
    source: str = "user_dictamen_panel",
) -> Dict[str, Any]:
    """Aplica decisiones parciales o batch sobre risk_decisions_v1."""
    record = normalize_risk_decisions(existing)
    decisions: Dict[str, Any] = dict(record.get("decisions") or {})
    now = datetime.now(timezone.utc).isoformat()

    for upd in decision_updates or []:
        if not isinstance(upd, dict):
            continue
        rid = str(upd.get("risk_id") or "").strip()
        status = str(upd.get("status") or "").strip().lower()
        if not rid or status not in ("accepted", "rejected", "pending"):
            continue
        decisions[rid] = {
            "risk_id": rid,
            "status": status,
            "user_note": (upd.get("user_note") or "").strip() or None,
            "decided_at": now,
            "source": source,
        }

    batch = record.get("batch")
    if batch_action in ("continue_assuming_risks", "stop_expediente"):
        pending_count = sum(
            1 for d in decisions.values() if str(d.get("status") or "") == "pending"
        )
        batch = {
            "action": batch_action,
            "pending_count_at_decision": pending_count,
            "decided_at": now,
            "source": source,
        }

    return {
        "schema_version": "risk_decisions_v1",
        "decisions": decisions,
        "batch": batch,
    }


def can_continue_with_risks(
    forensic_risks: Dict[str, Any],
    risk_decisions: Optional[Dict[str, Any]],
) -> bool:
    """True si no hay blocking pendientes sin aceptar."""
    merged = merge_risk_decisions_into_items(forensic_risks, risk_decisions)
    for item in merged.get("items") or []:
        if item.get("risk_severity") != "blocking":
            continue
        st = item.get("decision_status")
        if st not in ("accepted",):
            return False
    return True
