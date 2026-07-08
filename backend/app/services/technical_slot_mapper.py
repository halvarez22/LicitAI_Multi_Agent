"""
Mapeo HRU de slots técnicos desde compliance / catálogo / política (F9.2).

Sin hardcode por licitación.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.obra_chat_queue_policy import is_obra_session

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "technical_capture_policy.json"
)

_UPLOAD_ONLY_RE = re.compile(
    r"(?i)\b(" + "|".join(
        re.escape(m).replace(r"\ ", r"\s+")
        for m in (
            "experiencia",
            "trabajos similares",
            "capacidad tecnica",
            "capacidad técnica",
            "anexo t-2",
            "anexo t-b-2",
            "t-2",
            "t-b-2",
        )
    )
    + r")\b"
)


@lru_cache(maxsize=1)
def load_technical_capture_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _norm(text: str) -> str:
    raw = (text or "").strip().lower()
    nk = unicodedata.normalize("NFD", raw)
    t = "".join(c for c in nk if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def stable_concept_key(label: str, slot_kind: str) -> str:
    """Clave estable universal para merge idempotente."""
    slug = re.sub(r"[^a-z0-9]+", "_", _norm(label)).strip("_")[:80]
    kind = _norm(slot_kind) or "free_text_annex"
    return f"tech|{kind}|{slug or 'slot'}"


def infer_slot_kind(label: str, policy: Optional[Dict[str, Any]] = None) -> str:
    pol = policy or load_technical_capture_policy()
    text = _norm(label)
    for rule in pol.get("slot_kind_inference") or []:
        if not isinstance(rule, dict):
            continue
        kind = str(rule.get("slot_kind") or "")
        for marker in rule.get("label_markers") or []:
            if _norm(str(marker)) in text:
                return kind or "free_text_annex"
    return "free_text_annex"


def resolve_capture_mode(
    label: str,
    slot_kind: str,
    session_state: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
) -> str:
    pol = policy or load_technical_capture_policy()
    text = _norm(label)
    if slot_kind in (pol.get("upload_only_slot_kinds") or []):
        return "upload_only"
    for marker in pol.get("upload_only_label_markers") or []:
        if _norm(str(marker)) in text:
            return "upload_only"
    if is_obra_session(session_state) and _UPLOAD_ONLY_RE.search(label or ""):
        return "upload_only"
    return "chat_natural"


def _compliance_items(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    cml = session_state.get("compliance_master_list")
    if not isinstance(cml, dict):
        analysis = session_state.get("analysis") or {}
        if isinstance(analysis.get("results"), dict):
            cml = analysis["results"].get("analysis", {}).get("compliance_master_list")
    if not isinstance(cml, dict):
        return []
    pol = load_technical_capture_policy()
    allowed = {str(a).lower() for a in (pol.get("compliance_action_allow") or [])}
    out: List[Dict[str, Any]] = []
    for category in ("tecnico", "formatos"):
        for raw in cml.get(category) or []:
            if not isinstance(raw, dict):
                continue
            action = str(
                raw.get("tipo_accion")
                or raw.get("accion")
                or raw.get("action")
                or ""
            ).lower()
            if allowed and action and action not in allowed:
                continue
            label = str(
                raw.get("nombre")
                or raw.get("descripcion")
                or raw.get("titulo")
                or raw.get("id")
                or ""
            ).strip()
            if not label:
                continue
            from app.services.expediente_mission_policy import is_document_shell_technical_label

            if is_document_shell_technical_label(label):
                continue
            slot_kind = infer_slot_kind(label)
            if category == "formatos" and slot_kind == "free_text_annex":
                slot_kind = "admin_format"
            out.append(
                {
                    "label": label,
                    "slot_kind": slot_kind,
                    "source": f"compliance_master_list.{category}",
                    "required_for_generation": action in allowed or category == "tecnico",
                    "compliance_id": str(raw.get("id") or ""),
                }
            )
    return out


def _policy_baseline_slots(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Slots estructurales mínimos cuando compliance no lista campos redactables en chat."""
    from app.services.expediente_mission_policy import use_baseline_when_only_shells

    items = _compliance_items(session_state)
    if items:
        return []
    if not use_baseline_when_only_shells():
        return []
    return [
        {
            "label": "Metodología de ejecución",
            "slot_kind": "methodology",
            "source": "technical_capture_policy.baseline",
            "required_for_generation": True,
        },
        {
            "label": "Personal y dotación",
            "slot_kind": "workforce",
            "source": "technical_capture_policy.baseline",
            "required_for_generation": True,
        },
        {
            "label": "Equipos y herramientas",
            "slot_kind": "equipment",
            "source": "technical_capture_policy.baseline",
            "required_for_generation": True,
        },
    ]


def build_technical_slot_inventory(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Inventario merge idempotente de slots técnicos detectados."""
    seen: Dict[str, Dict[str, Any]] = {}
    for raw in _compliance_items(session_state) + _policy_baseline_slots(session_state):
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        slot_kind = str(raw.get("slot_kind") or infer_slot_kind(label))
        key = stable_concept_key(label, slot_kind)
        capture_mode = resolve_capture_mode(label, slot_kind, session_state)
        if key not in seen:
            seen[key] = {
                "concept_key": key,
                "label": label,
                "slot_kind": slot_kind,
                "capture_mode": capture_mode,
                "required_for_generation": bool(raw.get("required_for_generation", True)),
                "source_hint": str(raw.get("source") or ""),
            }
    return sorted(seen.values(), key=lambda s: str(s.get("concept_key") or ""))


def technical_capture_status(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Resumen de cobertura de slots técnicos."""
    slots = build_technical_slot_inventory(session_state)
    inputs = session_state.get("technical_user_inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    total = len(slots)
    filled = 0
    upload_only = 0
    for slot in slots:
        key = str(slot.get("concept_key") or "")
        mode = str(slot.get("capture_mode") or "chat_natural")
        val = inputs.get(key)
        if mode == "upload_only":
            upload_only += 1
            if inputs.get(f"{key}__upload_ack") or val:
                filled += 1
            continue
        if val is not None and str(val).strip():
            filled += 1
    missing = max(0, total - filled)
    pending_tech = sum(
        1
        for q in (session_state.get("pending_questions") or [])
        if str(q.get("type") or "") == "technical_slot"
    )
    capture_complete = total > 0 and missing == 0 and pending_tech == 0
    return {
        "total": total,
        "filled": filled,
        "missing": missing,
        "upload_only": upload_only,
        "pending_technical": pending_tech,
        "capture_complete": capture_complete,
    }
