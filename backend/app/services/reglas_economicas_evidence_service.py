"""
Evidencia HRU para reglas_economicas del Analista — ancla en origen, un solo motor forense.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.analyst_output_normalize import (
    _REGLAS_ECONOMICAS_KEYS,
    _REGLAS_ALIASES,
    _coerce_str,
    _norm_key,
)
from app.services.economic_alert_classifier import (
    _compile,
    _load_policy,
    _matches,
    classify_economic_alert_text,
    disambiguate_subtype_with_evidence,
    ux_reason_for_subtype,
)
from app.services.economic_risk_evidence_v1 import (
    MODE_INDEX_VERIFIED,
    build_evidence_v1,
)

SCHEMA_VERSION = "reglas_economicas_evidence_v1"
_DEFAULT = "No especificado"

SEMANTIC_EXPERIENCE = "experience_amount"
SEMANTIC_TABULAR = "tabular_reference"
SEMANTIC_GENERIC = "generic_economic"
SEMANTIC_MISMATCH = "semantic_mismatch"


def _canonical_rule_key(raw_key: str) -> Optional[str]:
    nk = _norm_key(raw_key)
    if nk in _REGLAS_ECONOMICAS_KEYS:
        return nk
    return _REGLAS_ALIASES.get(nk)


def _value_from_raw(raw: Any) -> str:
    if isinstance(raw, dict):
        return _coerce_str(raw.get("value") or raw.get("texto") or raw.get("text"), _DEFAULT)
    return _coerce_str(raw, _DEFAULT)


def _anchor_from_raw(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {
        "page": raw.get("page"),
        "snippet": raw.get("snippet"),
        "source": raw.get("source"),
    }


def classify_semantic_class(rule_key: str, value: str, snippet: Optional[str]) -> str:
    """Clasifica semántica del fragmento (experiencia vs tabular vs genérico)."""
    blob = f"{value} {snippet or ''}".strip()
    if _matches(blob, _compile("experience_amount_patterns")):
        return SEMANTIC_EXPERIENCE
    if rule_key == "referencia_partidas_anexos_citados" or _matches(
        blob, _compile("tabular_reference_patterns")
    ):
        return SEMANTIC_TABULAR
    return SEMANTIC_GENERIC


def check_semantic_promotion(
    rule_key: str,
    semantic_class: str,
    evidence_mode: str,
) -> Tuple[bool, Optional[str]]:
    """
    Decide si una regla verificada en índice puede promoverse a alerta forense.
    Evita anclar montos de experiencia como presupuesto/partidas.
    """
    if evidence_mode != MODE_INDEX_VERIFIED:
        return False, "EVIDENCE_NOT_INDEX_VERIFIED"

    expected_map = _load_policy().get("regla_key_expected_semantics") or {}
    expected = str(expected_map.get(rule_key) or "generic_economic")

    if semantic_class == SEMANTIC_EXPERIENCE and expected in (
        "tabular_reference",
        "offer_floor_or_importe",
        "budget_linkage",
    ):
        return False, "REGULA_SEMANTIC_MISMATCH"

    if rule_key == "referencia_partidas_anexos_citados" and semantic_class == SEMANTIC_EXPERIENCE:
        return False, "REGULA_SEMANTIC_MISMATCH"

    if expected == "period" and semantic_class == SEMANTIC_EXPERIENCE:
        return False, "REGULA_SEMANTIC_MISMATCH"

    return True, None


async def verify_regla_item(
    session_id: str,
    rule_key: str,
    value: str,
    anchor: Dict[str, Any],
    *,
    memory: Any = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resuelve evidencia forense para una regla económica."""
    if not value or value == _DEFAULT:
        return build_evidence_v1({"match_confidence": "none"}, literal=value)

    risk_ctx = {k: v for k, v in anchor.items() if v is not None}
    try:
        from app.services.forensic_risk_evidence_service import resolve_forensic_risk_evidence

        raw_ev = await resolve_forensic_risk_evidence(
            session_id,
            value,
            risk_ctx=risk_ctx,
            session_state=session_state,
            memory=memory,
        )
    except Exception:
        raw_ev = {"match_confidence": "none", "provenance": "regla_verify_error"}

    return build_evidence_v1(raw_ev, literal=value)


async def build_reglas_economicas_evidence_v1(
    session_id: str,
    raw_reglas: Any,
    *,
    memory: Any = None,
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Construye bloque reglas_economicas_evidence_v1 sin alterar reglas_economicas str legacy.
    """
    items: Dict[str, Any] = {}
    if not isinstance(raw_reglas, dict):
        raw_reglas = {}

    canonical_raw: Dict[str, Any] = {}
    for rk, rv in raw_reglas.items():
        canon = _canonical_rule_key(str(rk))
        if canon:
            canonical_raw[canon] = rv

    stats = {
        "total": 0,
        "index_verified": 0,
        "promotion_eligible": 0,
        "inference_only": 0,
        "semantic_mismatch": 0,
    }

    for key in _REGLAS_ECONOMICAS_KEYS:
        raw = canonical_raw.get(key)
        if raw is None:
            continue
        value = _value_from_raw(raw)
        if not value or value == _DEFAULT:
            continue

        stats["total"] += 1
        anchor = _anchor_from_raw(raw)
        evidence_v1 = await verify_regla_item(
            session_id,
            key,
            value,
            anchor,
            memory=memory,
            session_state=session_state,
        )
        snippet = str(evidence_v1.get("snippet") or anchor.get("snippet") or "")
        semantic_class = classify_semantic_class(key, value, snippet or None)
        evidence_mode = str(evidence_v1.get("evidence_mode") or "inference_only")

        if evidence_mode == MODE_INDEX_VERIFIED:
            stats["index_verified"] += 1
        else:
            stats["inference_only"] += 1

        promotion_ok, block_reason = check_semantic_promotion(key, semantic_class, evidence_mode)
        if not promotion_ok and block_reason == "REGULA_SEMANTIC_MISMATCH":
            stats["semantic_mismatch"] += 1
            semantic_class = SEMANTIC_MISMATCH
        if promotion_ok:
            stats["promotion_eligible"] += 1

        subtype = disambiguate_subtype_with_evidence(
            classify_economic_alert_text(value),
            value,
            snippet or None,
        )

        items[key] = {
            "rule_key": key,
            "value": value,
            "page": evidence_v1.get("page"),
            "snippet": evidence_v1.get("snippet"),
            "source": evidence_v1.get("source"),
            "evidence_v1": evidence_v1,
            "semantic_class": semantic_class,
            "promotion_eligible": promotion_ok,
            "promotion_block_reason": block_reason,
            "alert_subtype": subtype,
            "risk_reason_ux": ux_reason_for_subtype(subtype),
            "legacy_format": not isinstance(raw, dict),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "stats": stats,
    }


def build_forensic_alerts_from_evidence_block(
    evidence_block: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Genera alertas enriquecidas solo desde reglas promotion_eligible."""
    if not isinstance(evidence_block, dict):
        return []
    out: List[Dict[str, Any]] = []
    for key, item in (evidence_block.get("items") or {}).items():
        if not isinstance(item, dict) or not item.get("promotion_eligible"):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        ev = item.get("evidence_v1") or {}
        subtype = str(item.get("alert_subtype") or classify_economic_alert_text(value))
        out.append(
            {
                "texto": value,
                "alert_subtype": subtype,
                "page": ev.get("page"),
                "snippet": ev.get("snippet"),
                "source": ev.get("source"),
                "evidence_v1": ev,
                "rule_key": key,
                "semantic_class": item.get("semantic_class"),
                "risk_reason_ux": item.get("risk_reason_ux"),
                "include_in_forensic_risks": True,
                "provenance": "reglas_economicas_evidence_v1",
            }
        )
    return out
