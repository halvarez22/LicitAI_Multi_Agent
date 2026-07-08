"""
Verdad canónica versionada de datos técnicos (technical_canonical_v1) — F9.1.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.services.technical_slot_mapper import (
    build_technical_slot_inventory,
    technical_capture_status,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "technical_canonical_v1.json"
)

SCHEMA_VERSION = "technical-canonical-v1.0.0"


@lru_cache(maxsize=1)
def load_technical_canonical_schema() -> Dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def precedence_rank_map() -> Dict[str, int]:
    raw = load_technical_canonical_schema().get("precedence_rank") or {}
    return {str(k): int(v) for k, v in raw.items()}


def build_canonical_item(
    *,
    concept_key: str,
    label: str,
    slot_kind: str,
    value_text: Optional[str],
    capture_mode: str,
    required_for_generation: bool,
    source_channel: str,
    provenance_ui: Optional[Dict[str, Any]] = None,
    status: str = "pending",
) -> Dict[str, Any]:
    rank = precedence_rank_map().get(source_channel, 0)
    captured = bool(value_text and str(value_text).strip())
    if capture_mode == "upload_only" and status != "upload_satisfied":
        st = "upload_satisfied" if captured else "pending"
    else:
        st = "captured" if captured else status
    return {
        "concept_key": concept_key,
        "label": label,
        "slot_kind": slot_kind,
        "value_text": value_text,
        "capture_mode": capture_mode,
        "required_for_generation": required_for_generation,
        "status": st,
        "source_channel": source_channel,
        "precedence_rank": rank,
        "provenance_ui": provenance_ui or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def merge_technical_canonical_v1(
    existing: Optional[Dict[str, Any]],
    incoming_items: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    base_items: Dict[str, Dict[str, Any]] = {}
    if isinstance(existing, dict):
        for raw in existing.get("items") or []:
            if isinstance(raw, dict):
                key = str(raw.get("concept_key") or "")
                if key:
                    base_items[key] = dict(raw)
    for raw in incoming_items or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("concept_key") or "")
        if not key:
            continue
        prev = base_items.get(key)
        if prev is None:
            base_items[key] = dict(raw)
            continue
        if int(raw.get("precedence_rank") or 0) >= int(prev.get("precedence_rank") or 0):
            base_items[key] = dict(raw)
    items = sorted(base_items.values(), key=lambda i: str(i.get("concept_key") or ""))
    captured = sum(1 for i in items if i.get("status") in ("captured", "upload_satisfied"))
    return {
        "schema_version": SCHEMA_VERSION,
        "items": items,
        "summary": {
            "total": len(items),
            "captured": captured,
            "pending": max(0, len(items) - captured),
        },
    }


def build_technical_canonical_v1_from_session(session_state: Dict[str, Any]) -> Dict[str, Any]:
    inputs = session_state.get("technical_user_inputs") or {}
    overrides = session_state.get("technical_user_overrides") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    if not isinstance(overrides, dict):
        overrides = {}

    incoming: List[Dict[str, Any]] = []
    for slot in build_technical_slot_inventory(session_state):
        key = str(slot.get("concept_key") or "")
        if not key:
            continue
        value = inputs.get(key)
        ov = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
        channel = str(ov.get("source") or "inference")
        if value is not None and str(value).strip():
            channel = "user_direct" if ov else "user_chat"
        incoming.append(
            build_canonical_item(
                concept_key=key,
                label=str(slot.get("label") or key),
                slot_kind=str(slot.get("slot_kind") or "free_text_annex"),
                value_text=str(value).strip() if value is not None else None,
                capture_mode=str(slot.get("capture_mode") or "chat_natural"),
                required_for_generation=bool(slot.get("required_for_generation", True)),
                source_channel=channel if channel in precedence_rank_map() else "user_chat",
                provenance_ui={
                    "source": channel,
                    "original_phrase": str(ov.get("original_phrase") or "")[:240],
                    "source_hint": str(slot.get("source_hint") or ""),
                },
            )
        )

    existing = session_state.get("technical_canonical_v1")
    merged = merge_technical_canonical_v1(
        existing if isinstance(existing, dict) else None,
        incoming,
    )
    cap = technical_capture_status(session_state)
    merged["summary"]["capture_complete"] = bool(cap.get("capture_complete"))
    merged["summary"]["matrix_missing"] = int(cap.get("missing") or 0)
    return merged


def sync_technical_canonical_v1(session_state: Dict[str, Any]) -> Dict[str, Any]:
    return {"technical_canonical_v1": build_technical_canonical_v1_from_session(session_state)}


def build_technical_capture_v1_api_payload(session_state: Dict[str, Any]) -> Dict[str, Any]:
    canonical = build_technical_canonical_v1_from_session(session_state)
    cap = technical_capture_status(session_state)
    return {
        "schema_version": SCHEMA_VERSION,
        "capture_status": cap,
        "canonical": canonical,
        "capture_mode": str(session_state.get("technical_capture_mode") or ""),
    }


def register_technical_capture_update(
    session_state: Dict[str, Any],
    *,
    concept_key: str,
    label: str,
    value_text: str,
    slot_kind: str = "free_text_annex",
    capture_mode: str = "chat_natural",
    source_channel: str = "user_chat",
    original_phrase: str = "",
) -> Dict[str, Any]:
    inputs = dict(session_state.get("technical_user_inputs") or {})
    inputs[concept_key] = value_text
    overrides = dict(session_state.get("technical_user_overrides") or {})
    overrides[concept_key] = {
        "source": source_channel,
        "original_phrase": (original_phrase or "")[:240],
    }
    item = build_canonical_item(
        concept_key=concept_key,
        label=label,
        slot_kind=slot_kind,
        value_text=value_text,
        capture_mode=capture_mode,
        required_for_generation=True,
        source_channel=source_channel if source_channel in precedence_rank_map() else "user_chat",
    )
    existing = session_state.get("technical_canonical_v1")
    canonical = merge_technical_canonical_v1(
        existing if isinstance(existing, dict) else None,
        [item],
    )
    merged = {
        **session_state,
        "technical_user_inputs": inputs,
        "technical_user_overrides": overrides,
        "technical_canonical_v1": canonical,
    }
    return {
        "technical_user_inputs": inputs,
        "technical_user_overrides": overrides,
        "technical_canonical_v1": canonical,
        "technical_capture_v1": build_technical_capture_v1_api_payload(merged),
    }


def gate_technical_generation_chat_first(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Bloquea TechnicalWriter si faltan slots ``required_for_generation`` (modo chat_first).
    """
    from app.config.settings import settings

    if not bool(getattr(settings, "TECHNICAL_CHAT_FIRST", True)):
        return None
    canonical = build_technical_canonical_v1_from_session(session_state)
    missing = [
        i
        for i in (canonical.get("items") or [])
        if isinstance(i, dict)
        and i.get("required_for_generation")
        and i.get("status") not in ("captured", "upload_satisfied", "deferred")
        and str(i.get("capture_mode") or "") != "upload_only"
    ]
    if not missing:
        return None
    labels = [str(i.get("label") or i.get("concept_key")) for i in missing[:6]]
    from app.services.technical_capture_ux import build_generar_tecnica_incomplete_message

    return {
        "message": build_generar_tecnica_incomplete_message(session_state),
        "missing_labels": labels,
        "technical_capture_v1": build_technical_capture_v1_api_payload(session_state),
    }
