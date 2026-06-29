"""
Clasificación HRU de alertas económicas: subtipo, deduplicación, exclusión de ruido convocante.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

AlertSubtype = str

SUBTYPE_OFFER_FLOOR = "offer_floor"
SUBTYPE_CONVOCANTE_BUDGET = "convocante_budget"
SUBTYPE_GUARANTEE_INSURANCE = "guarantee_insurance"
SUBTYPE_AMBIGUOUS_PRESUPUESTO = "ambiguous_presupuesto"
SUBTYPE_BASES_COHERENCE = "bases_coherence_hint"
SUBTYPE_SESSION_CANONICAL = "session_canonical_hint"
SUBTYPE_GENERIC = "generic_economic"

# Fallback mínimo si policy no carga (tests offline)
_UX_FALLBACK: Dict[str, str] = {
    SUBTYPE_GENERIC: (
        "El agente económico detectó una condición relevante para tu oferta. "
        "Contrasta con tu propuesta y expediente."
    ),
}


def ux_reason_for_subtype(subtype: str) -> str:
    """UX centralizado desde policy JSON (HRU)."""
    policy = _load_policy()
    reasons = policy.get("ux_reason_by_subtype") or {}
    return str(
        reasons.get(subtype)
        or reasons.get(SUBTYPE_GENERIC)
        or _UX_FALLBACK.get(SUBTYPE_GENERIC)
        or ""
    )


# Compatibilidad regresión: alias histórico
UX_REASON_BY_SUBTYPE: Dict[str, str] = {}


@lru_cache(maxsize=1)
def _load_policy() -> Dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "contracts" / "economic_alert_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _compile(key: str) -> List[re.Pattern[str]]:
    out: List[re.Pattern[str]] = []
    for pat in _load_policy().get(key) or []:
        try:
            out.append(re.compile(pat))
        except re.error:
            continue
    return out


def _matches(text: str, patterns: List[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def alert_fingerprint(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or "").lower().strip())
    t = re.sub(r"[^\w\s$.,]", "", t)
    # Normalizar montos 1,000,000 vs 1000000
    t = re.sub(r"(\d)[,\.](?=\d{3})", r"\1", t)
    return t[:240]


def _classify_by_prefix(text: str) -> Optional[AlertSubtype]:
    blob = str(text or "").strip()
    if not blob:
        return None
    for prefix, subtype in (_load_policy().get("prefix_subtypes") or {}).items():
        if blob.startswith(str(prefix)):
            return str(subtype)
    return None


def classify_economic_alert_text(text: str) -> AlertSubtype:
    blob = str(text or "").strip()
    if not blob:
        return SUBTYPE_GENERIC
    by_prefix = _classify_by_prefix(blob)
    if by_prefix:
        return by_prefix
    if _matches(blob, _compile("convocante_budget_patterns")):
        return SUBTYPE_CONVOCANTE_BUDGET
    if _matches(blob, _compile("guarantee_insurance_patterns")):
        return SUBTYPE_GUARANTEE_INSURANCE
    if _matches(blob, _compile("offer_floor_patterns")):
        return SUBTYPE_OFFER_FLOOR
    if _matches(blob, _compile("presupuesto_disambiguation_trigger_patterns")):
        return SUBTYPE_AMBIGUOUS_PRESUPUESTO
    if _matches(blob, _compile("ambiguous_presupuesto_patterns")):
        return SUBTYPE_AMBIGUOUS_PRESUPUESTO
    return SUBTYPE_GENERIC


def needs_presupuesto_disambiguation(text: str) -> bool:
    return _matches(str(text or "").strip(), _compile("presupuesto_disambiguation_trigger_patterns"))


def disambiguate_subtype_with_evidence(
    base_subtype: str,
    literal: str,
    snippet: Optional[str] = None,
) -> AlertSubtype:
    """
    Refina subtipo usando fragmento indexado de las bases (HRU).
    Sin snippet: no asume piso de oferta solo por el literal ambiguo.
    """
    sn = str(snippet or "").strip()
    if sn:
        if _matches(sn, _compile("snippet_convocante_budget_patterns")):
            return SUBTYPE_CONVOCANTE_BUDGET
        if _matches(sn, _compile("snippet_offer_floor_patterns")):
            return SUBTYPE_OFFER_FLOOR
        combined = f"{literal} {sn}"
        if _matches(combined, _compile("snippet_offer_floor_patterns")):
            return SUBTYPE_OFFER_FLOOR
        if _matches(combined, _compile("snippet_convocante_budget_patterns")):
            return SUBTYPE_CONVOCANTE_BUDGET
    if needs_presupuesto_disambiguation(literal):
        return SUBTYPE_AMBIGUOUS_PRESUPUESTO
    return base_subtype  # type: ignore[return-value]


def resolve_session_currency(session_state: Optional[Dict[str, Any]]) -> str:
    """Moneda desde payload económico de sesión; sin hardcode MXN."""
    if not isinstance(session_state, dict):
        return str(_load_policy().get("default_currency_fallback") or "").strip()
    tc = session_state.get("tasks_completed")
    if isinstance(tc, dict):
        for agent_key in ("economic", "economic_proposal", "economic_writer"):
            agent = tc.get(agent_key)
            if not isinstance(agent, dict):
                continue
            data = agent.get("data") if isinstance(agent.get("data"), dict) else agent
            if isinstance(data, dict):
                cur = data.get("currency") or data.get("moneda")
                if cur and str(cur).strip():
                    return str(cur).strip()
    er = session_state.get("execution_results")
    if isinstance(er, dict):
        ep = er.get("economic_proposal") or er.get("economic")
        if isinstance(ep, dict):
            cur = ep.get("currency") or ep.get("moneda")
            if cur and str(cur).strip():
                return str(cur).strip()
    return str(_load_policy().get("default_currency_fallback") or "").strip()


def should_include_in_forensic_risks(subtype: str) -> bool:
    excluded = set(_load_policy().get("exclude_from_forensic_risks_subtypes") or [])
    return subtype not in excluded


def include_alert_in_forensic_risks(alert_item: Dict[str, Any]) -> bool:
    """
    Gate HRU: solo promover a panel HITL si policy lo permite y hay ancla index_verified.
    """
    if not isinstance(alert_item, dict):
        return False
    if alert_item.get("include_in_forensic_risks") is False:
        return False
    subtype = str(alert_item.get("alert_subtype") or classify_economic_alert_text(
        str(alert_item.get("texto") or "")
    ))
    if not should_include_in_forensic_risks(subtype):
        return False
    policy = _load_policy()
    if policy.get("promotion_requires_index_verified"):
        ev = alert_item.get("evidence_v1") or {}
        mode = str(ev.get("evidence_mode") or alert_item.get("evidence_mode") or "")
        if mode != "index_verified":
            return False
    return True


def risk_severity_for_subtype(subtype: str) -> str:
    sev_map = _load_policy().get("severity_by_subtype") or {}
    if subtype in sev_map:
        return str(sev_map[subtype])
    if subtype == SUBTYPE_OFFER_FLOOR:
        return "blocking"
    if subtype in (SUBTYPE_GUARANTEE_INSURANCE, SUBTYPE_AMBIGUOUS_PRESUPUESTO):
        return "high"
    if subtype == SUBTYPE_CONVOCANTE_BUDGET:
        return "medium"
    if subtype in (SUBTYPE_BASES_COHERENCE, SUBTYPE_SESSION_CANONICAL):
        return "medium"
    return "high"


def sanitize_economic_causal(h: Dict[str, Any]) -> Dict[str, Any]:
    """Re-clasifica causal económica y ajusta isRisk según política HRU."""
    cat = str(h.get("category") or "").lower()
    if cat not in ("economic", "economic_gap_context", "economic_context"):
        return h
    texto = h.get("texto")
    if isinstance(texto, dict):
        norm = normalize_economic_alert({**texto, **h})
    else:
        norm = normalize_economic_alert({**h, "texto": texto})
    include = bool(norm.get("include_in_forensic_risks"))
    out = {
        **h,
        "alert_subtype": norm.get("alert_subtype"),
        "risk_reason_ux": norm.get("risk_reason_ux"),
    }
    if not include:
        out["isRisk"] = False
        out["category"] = "economic_context"
        if str(out.get("tipo") or "").startswith("💰"):
            out["tipo"] = "📋 CONTEXTO ECONÓMICO"
    return out


def sanitize_economic_causales(causales: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [sanitize_economic_causal(h) for h in (causales or []) if isinstance(h, dict)]


def normalize_economic_alert(raw: Any, *, index: int = 0) -> Dict[str, Any]:
    """Convierte alerta cruda (str o dict) en ítem enriquecido."""
    if isinstance(raw, dict):
        text = (
            raw.get("descripcion")
            or raw.get("texto")
            or raw.get("message")
            or raw.get("alerta")
            or ""
        )
        page = raw.get("page")
        snippet = raw.get("snippet")
        alert_id = raw.get("id")
    else:
        text = str(raw or "").strip()
        page = None
        snippet = None
        alert_id = None

    subtype = classify_economic_alert_text(text)
    fp = alert_fingerprint(text)
    rid = alert_id or f"econ-{fp[:48] or index}"
    snippet_str = str(snippet or "").strip() or None
    refined_subtype = disambiguate_subtype_with_evidence(subtype, text, snippet_str)

    item = {
        "texto": text,
        "alert_subtype": refined_subtype,
        "alert_fingerprint": fp,
        "risk_reason_ux": ux_reason_for_subtype(refined_subtype),
        "include_in_forensic_risks": should_include_in_forensic_risks(refined_subtype),
        "suggested_severity": risk_severity_for_subtype(refined_subtype),
        "page": page,
        "snippet": snippet,
        "id": rid,
    }
    if isinstance(raw, dict):
        if raw.get("evidence_v1"):
            item["evidence_v1"] = raw.get("evidence_v1")
        for k in ("source", "rule_key", "semantic_class", "provenance"):
            if raw.get(k) is not None:
                item[k] = raw.get(k)
    item["include_in_forensic_risks"] = include_alert_in_forensic_risks(item)
    return item


def dedupe_normalized_alerts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for item in items:
        fp = item.get("alert_fingerprint") or alert_fingerprint(str(item.get("texto") or ""))
        if not fp or fp in seen:
            continue
        seen.add(fp)
        out.append(item)
    return out


def normalize_and_dedupe_economic_alerts(raw_list: List[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (forensic_risk_alerts, excluded_context_alerts).
    """
    normalized = [normalize_economic_alert(a, index=i) for i, a in enumerate(raw_list or []) if a]
    deduped = dedupe_normalized_alerts(normalized)
    forensic: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for item in deduped:
        if item.get("include_in_forensic_risks"):
            forensic.append(item)
        else:
            excluded.append(item)
    return forensic, excluded
