"""
Verdad canónica versionada de precios (economic_canonical_v1).

Merge idempotente por ``concept_key`` (derivado del field estructurado universal).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.services.economic_capture_matrix_service import (
    build_cell_provenance_ui,
    economic_capture_status,
)
from app.services.structured_economic_price_mapper import build_structured_price_slots

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "economic_canonical_v1.json"
)

SCHEMA_VERSION = "economic-canonical-v1.0.0"


@lru_cache(maxsize=1)
def load_economic_canonical_schema() -> Dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def precedence_rank_map() -> Dict[str, int]:
    raw = load_economic_canonical_schema().get("precedence_rank") or {}
    return {str(k): int(v) for k, v in raw.items()}


def concept_key_from_field(field: str) -> str:
    """Clave estable universal para merge idempotente."""
    return str(field or "").strip()


def _safe_amount(value: Any) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _channel_from_overrides(
    field: str,
    overrides: Dict[str, Any],
    default: str = "user_chat",
) -> str:
    raw = overrides.get(field)
    if isinstance(raw, dict):
        return str(raw.get("source") or raw.get("channel") or default)
    return default


def build_canonical_item(
    *,
    concept_key: str,
    label: str,
    amount_mxn: Optional[float],
    source_channel: str,
    provenance_ui: Optional[Dict[str, Any]] = None,
    status: str = "pending",
) -> Dict[str, Any]:
    rank = precedence_rank_map().get(source_channel, 0)
    return {
        "concept_key": concept_key,
        "label": label,
        "amount_mxn": amount_mxn,
        "status": status if amount_mxn is None else "captured",
        "source_channel": source_channel,
        "precedence_rank": rank,
        "provenance_ui": provenance_ui or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_economic_canonical_v1(
    existing: Optional[Dict[str, Any]],
    incoming_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge idempotente: gana el ítem con mayor ``precedence_rank`` por concept_key.
    """
    base_items: Dict[str, Dict[str, Any]] = {}
    if isinstance(existing, dict):
        for raw in existing.get("items") or []:
            if not isinstance(raw, dict):
                continue
            key = concept_key_from_field(str(raw.get("concept_key") or ""))
            if key:
                base_items[key] = dict(raw)

    for raw in incoming_items or []:
        if not isinstance(raw, dict):
            continue
        key = concept_key_from_field(str(raw.get("concept_key") or ""))
        if not key:
            continue
        prev = base_items.get(key)
        if prev is None:
            base_items[key] = dict(raw)
            continue
        prev_rank = int(prev.get("precedence_rank") or 0)
        new_rank = int(raw.get("precedence_rank") or 0)
        if new_rank >= prev_rank:
            base_items[key] = dict(raw)

    items = sorted(base_items.values(), key=lambda i: str(i.get("concept_key") or ""))
    captured = sum(1 for i in items if i.get("status") == "captured")
    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "summary": {
            "total": len(items),
            "captured": captured,
            "pending": max(0, len(items) - captured),
        },
    }


def build_economic_canonical_v1_from_session(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Construye canónico desde slots estructurados + ``economic_user_inputs``."""
    rows = list(session_state.get("session_line_items") or [])
    inputs = session_state.get("economic_user_inputs") or {}
    overrides = session_state.get("economic_user_overrides") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    if not isinstance(overrides, dict):
        overrides = {}

    concept_bucket = inputs.get("concept_prices") if isinstance(inputs.get("concept_prices"), dict) else {}

    def _amount_for_field(field: str) -> Optional[float]:
        val = _safe_amount(inputs.get(field))
        if val is not None:
            return val
        if field in concept_bucket:
            return _safe_amount(concept_bucket.get(field))
        return None

    slots = build_structured_price_slots(rows, inputs)
    incoming: List[Dict[str, Any]] = []
    for slot in slots:
        field = concept_key_from_field(str(slot.get("field") or ""))
        if not field:
            continue
        amount = _amount_for_field(field)
        if amount is None:
            amount = _safe_amount(slot.get("captured_price"))
        channel = _channel_from_overrides(field, overrides)
        if _amount_for_field(field) is not None:
            channel = "user_direct"
        prov = build_cell_provenance_ui(
            source_file=str(slot.get("source_name") or "anexo_economico"),
            sheet_name=slot.get("sheet_name"),
            row_index=slot.get("row_index"),
            column_role=str(slot.get("price_column_header") or ""),
            channel="user_direct" if channel.startswith("user") else "detected",
            filled=amount is not None,
        )
        incoming.append(
            build_canonical_item(
                concept_key=field,
                label=str(slot.get("label") or slot.get("concept_label") or field),
                amount_mxn=amount,
                source_channel=channel if channel in precedence_rank_map() else "user_direct",
                provenance_ui=prov,
            )
        )

    existing = session_state.get("economic_canonical_v1")
    merged = merge_economic_canonical_v1(existing if isinstance(existing, dict) else None, incoming)
    cap = economic_capture_status(session_state)
    merged["summary"]["capture_complete"] = bool(cap.get("capture_complete"))
    merged["summary"]["matrix_missing"] = int(cap.get("missing") or 0)
    from app.services.economic_calculation_service import attach_totals_to_canonical

    return attach_totals_to_canonical(merged, session_state=session_state)


def sync_economic_canonical_v1(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve actualización de sesión con canónico recalculado."""
    return {"economic_canonical_v1": build_economic_canonical_v1_from_session(session_state)}


def build_economic_capture_v1_api_payload(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Payload API para chat/UI: canónico + matriz + estado compacto.
    """
    canonical = build_economic_canonical_v1_from_session(session_state)
    cap = economic_capture_status(session_state)
    totals = canonical.get("totals") if isinstance(canonical.get("totals"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "capture_status": cap,
        "canonical": canonical,
        "totals": totals,
        "totals_provenance_ui": canonical.get("totals_provenance_ui") or {},
        "capture_mode": str(session_state.get("economic_capture_mode") or ""),
        "matrix_block_count": len(session_state.get("capture_matrix_blocks") or []),
    }


def register_canonical_price_update(
    session_state: Dict[str, Any],
    *,
    concept_key: str,
    label: str,
    amount_mxn: float,
    source_channel: str = "user_chat",
    original_phrase: str = "",
) -> Dict[str, Any]:
    """Persiste precio en inputs + merge canónico idempotente."""
    inputs = dict(session_state.get("economic_user_inputs") or {})
    inputs[concept_key] = amount_mxn
    overrides = dict(session_state.get("economic_user_overrides") or {})
    overrides[concept_key] = {
        "source": source_channel,
        "original_phrase": (original_phrase or "")[:240],
    }
    item = build_canonical_item(
        concept_key=concept_key,
        label=label,
        amount_mxn=amount_mxn,
        source_channel=source_channel if source_channel in precedence_rank_map() else "user_chat",
    )
    existing = session_state.get("economic_canonical_v1")
    canonical = merge_economic_canonical_v1(
        existing if isinstance(existing, dict) else None,
        [item],
    )
    merged = {
        **session_state,
        "economic_user_inputs": inputs,
        "economic_user_overrides": overrides,
        "economic_canonical_v1": canonical,
    }
    return {
        "economic_user_inputs": inputs,
        "economic_user_overrides": overrides,
        "economic_canonical_v1": canonical,
        "economic_capture_v1": build_economic_capture_v1_api_payload(merged),
    }
