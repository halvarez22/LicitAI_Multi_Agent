"""Mensajes UX centralizados del copiloto técnico (F9)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.services.chat_gate5_formatter import format_gate5_message
from app.services.technical_slot_mapper import (
    build_technical_slot_inventory,
    technical_capture_status,
)

_UX_PATH = Path(__file__).resolve().parents[1] / "contracts" / "chat_copilot_ux_messages.json"


@lru_cache(maxsize=1)
def load_chat_copilot_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _ux_technical() -> Dict[str, str]:
    raw = load_chat_copilot_ux_messages().get("technical_capture") or {}
    return {str(k): str(v) for k, v in raw.items()}


def format_technical_slots_table(session_state: Dict[str, Any], *, limit: int = 8) -> str:
    ux = _ux_technical()
    inputs = session_state.get("technical_user_inputs") or {}
    lines = [
        ux.get("matrix_header", "**Propuesta técnica pendiente**"),
        "",
        "| Requisito | Estado |",
        "|-----------|--------|",
    ]
    for slot in build_technical_slot_inventory(session_state)[:limit]:
        key = str(slot.get("concept_key") or "")
        from app.services.expediente_mission_policy import humanize_technical_slot_label

        label = humanize_technical_slot_label(
            str(slot.get("label") or key),
            str(slot.get("slot_kind") or ""),
        )
        mode = str(slot.get("capture_mode") or "chat_natural")
        if mode == "upload_only":
            st = ux.get("status_upload_only", "*(documento en Fuentes)*")
        elif inputs.get(key):
            st = ux.get("status_captured", "*(capturado)*")
        else:
            st = ux.get("status_pending", "*(pendiente)*")
        lines.append(f"| {label} | {st} |")
    return "\n".join(lines)


def list_missing_technical_labels(session_state: Dict[str, Any], *, limit: int = 6) -> List[str]:
    inputs = session_state.get("technical_user_inputs") or {}
    out: List[str] = []
    for slot in build_technical_slot_inventory(session_state):
        key = str(slot.get("concept_key") or "")
        mode = str(slot.get("capture_mode") or "chat_natural")
        if mode == "upload_only":
            continue
        if not inputs.get(key):
            from app.services.expediente_mission_policy import humanize_technical_slot_label

            out.append(
                humanize_technical_slot_label(
                    str(slot.get("label") or key),
                    str(slot.get("slot_kind") or ""),
                )
            )
        if len(out) >= limit:
            break
    return out


def build_technical_discovery_message(session_state: Dict[str, Any]) -> str:
    ux = _ux_technical()
    cap = technical_capture_status(session_state)
    name = str(session_state.get("name") or "esta licitación")
    table = format_technical_slots_table(session_state)
    status = ux.get("discovery_lead", "").format(
        session_name=name,
        n_missing=int(cap.get("missing") or 0),
    )
    return format_gate5_message(
        status=status,
        detail=table,
        cta=ux.get("cta_capture", ""),
    )


def build_technical_capture_confirmation_message(
    *,
    session_state: Dict[str, Any],
    label: str,
    value_text: str,
    next_label: str | None = None,
) -> str:
    ux = _ux_technical()
    cap = technical_capture_status(session_state)
    parts = [
        ux.get("slot_registered", "").format(label=label, value=value_text[:500]),
        "",
        ux.get("provenance_line", "Procedencia: tu mensaje en chat."),
    ]
    missing = int(cap.get("missing") or 0)
    if missing > 0 and next_label:
        parts.extend(
            [
                "",
                ux.get("next_missing", "").format(missing=missing),
                ux.get("next_slot", "").format(next_label=next_label),
            ]
        )
    elif missing > 0:
        parts.extend(["", ux.get("next_missing", "").format(missing=missing)])
    else:
        parts.extend(["", ux.get("capture_complete", "")])
    return "\n".join(p for p in parts if p is not None).strip()


def build_generar_tecnica_incomplete_message(session_state: Dict[str, Any]) -> str:
    ux = _ux_technical()
    cap = technical_capture_status(session_state)
    labels = list_missing_technical_labels(session_state)
    detail = ux.get("generar_incomplete_detail", "").format(
        filled=int(cap.get("filled") or 0),
        total=int(cap.get("total") or 0),
    )
    if labels:
        detail += "\n\n" + ux.get("missing_table_header", "")
        for lbl in labels:
            detail += "\n" + ux.get("missing_row", "").format(label=lbl)
    detail += "\n\n" + format_technical_slots_table(session_state, limit=6)
    return format_gate5_message(
        status=ux.get("generar_incomplete_lead", ""),
        detail=detail,
        cta=ux.get("cta_capture", ""),
    )


def build_dual_copilot_status_message(session_state: Dict[str, Any]) -> str:
    from app.services.economic_capture_matrix_service import economic_capture_status

    ux = _ux_technical()
    tech = technical_capture_status(session_state)
    eco = economic_capture_status(session_state)
    detail = ux.get("dual_status_body", "").format(
        tech_filled=int(tech.get("filled") or 0),
        tech_total=int(tech.get("total") or 0),
        tech_missing=int(tech.get("missing") or 0),
        eco_filled=int(eco.get("filled") or 0),
        eco_total=int(eco.get("total") or 0),
        eco_missing=int(eco.get("missing") or 0),
    )
    return format_gate5_message(
        status=ux.get("dual_status_lead", ""),
        detail=detail,
        cta=ux.get("dual_status_cta", ""),
    )
