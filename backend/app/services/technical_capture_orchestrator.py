"""
Orquestador HRU del copiloto técnico conversacional (F9.4).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.services.chat_gate5_formatter import format_gate5_message
from app.services.chat_stop_reason_map import sanitize_user_visible_text
from app.services.technical_canonical_v1 import (
    build_technical_capture_v1_api_payload,
    register_technical_capture_update,
    sync_technical_canonical_v1,
)
from app.services.technical_capture_ux import (
    build_dual_copilot_status_message,
    build_generar_tecnica_incomplete_message,
    build_technical_capture_confirmation_message,
    build_technical_discovery_message,
    load_chat_copilot_ux_messages,
)
from app.services.technical_slot_mapper import (
    build_technical_slot_inventory,
    infer_slot_kind,
    load_technical_capture_policy,
    stable_concept_key,
    technical_capture_status,
)


@dataclass
class TechnicalCaptureResult:
    handled: bool = False
    respuesta: str = ""
    tipo: str = "info"
    session_updates: Dict[str, Any] = field(default_factory=dict)
    technical_capture_v1: Optional[Dict[str, Any]] = None
    delegate_to_agent: Optional[str] = None


@dataclass
class GenerarTecnicaGateResult:
    should_block: bool = False
    message: str = ""
    capture_complete: bool = False
    materializing_lead: str = ""


def _norm(text: str) -> str:
    raw = (text or "").strip().lower()
    nk = unicodedata.normalize("NFD", raw)
    t = "".join(c for c in nk if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def _phrase_match(query: str, phrases: List[str]) -> bool:
    q = _norm(query)
    return any(_norm(p) in q for p in (phrases or []))


def gate_generar_tecnica_intent(session_state: Dict[str, Any]) -> GenerarTecnicaGateResult:
    cap = technical_capture_status(session_state)
    complete = bool(cap.get("capture_complete"))
    ux = (load_chat_copilot_ux_messages().get("technical_capture") or {})
    materializing = str(ux.get("generar_materializing") or "")
    if complete:
        return GenerarTecnicaGateResult(
            should_block=False,
            capture_complete=True,
            materializing_lead=materializing,
        )
    total = int(cap.get("total") or 0)
    if total <= 0:
        return GenerarTecnicaGateResult(should_block=False, capture_complete=False)
    return GenerarTecnicaGateResult(
        should_block=True,
        message=build_generar_tecnica_incomplete_message(session_state),
        capture_complete=False,
    )


def parse_technical_capture_phrase(query: str) -> Optional[Tuple[str, str, str]]:
    """
  Parsea frases tipo ``metodología: …`` → (slot_kind, value, prefix).
    """
    policy = load_technical_capture_policy()
    raw = (query or "").strip()
    for spec in policy.get("capture_prefixes") or []:
        if not isinstance(spec, dict):
            continue
        prefix = str(spec.get("prefix") or "")
        if not prefix:
            continue
        m = re.match(
            rf"^{re.escape(prefix)}\s*[:=\-]\s*(.+)$",
            raw,
            flags=re.IGNORECASE,
        )
        if m:
            value = m.group(1).strip()
            if value:
                return str(spec.get("slot_kind") or "free_text_annex"), value, prefix
    return None


def _next_pending_slot(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inputs = session_state.get("technical_user_inputs") or {}
    for slot in build_technical_slot_inventory(session_state):
        key = str(slot.get("concept_key") or "")
        if str(slot.get("capture_mode") or "") == "upload_only":
            continue
        if not inputs.get(key):
            return slot
    return None


def _apply_capture_value(
    session_state: Dict[str, Any],
    *,
    concept_key: str,
    label: str,
    slot_kind: str,
    capture_mode: str,
    value_text: str,
    original_phrase: str,
) -> Dict[str, Any]:
    updates = register_technical_capture_update(
        session_state,
        concept_key=concept_key,
        label=label,
        value_text=value_text,
        slot_kind=slot_kind,
        capture_mode=capture_mode,
        source_channel="user_chat",
        original_phrase=original_phrase,
    )
    updates.update(sync_technical_canonical_v1({**session_state, **updates}))
    return updates


def _try_handle_defer(query: str) -> Optional[TechnicalCaptureResult]:
    policy = load_technical_capture_policy()
    if not _phrase_match(query, list(policy.get("defer_capture_phrases") or [])):
        return None
    ux = (load_chat_copilot_ux_messages().get("technical_capture") or {})
    msg = format_gate5_message(
        status="Entendido — dejamos los datos técnicos para después.",
        detail=str(ux.get("defer_detail") or ""),
        cta=str(ux.get("cta_generate") or ""),
    )
    return TechnicalCaptureResult(handled=True, respuesta=msg, tipo="technical_deferred")


def _try_handle_dual_status(query: str, session_state: Dict[str, Any]) -> Optional[TechnicalCaptureResult]:
    policy = load_technical_capture_policy()
    if not _phrase_match(query, list(policy.get("dual_status_markers") or [])):
        return None
    return TechnicalCaptureResult(
        handled=True,
        respuesta=build_dual_copilot_status_message(session_state),
        tipo="copilot_dual_status",
        technical_capture_v1=build_technical_capture_v1_api_payload(session_state),
    )


def _try_handle_technical_status(query: str, session_state: Dict[str, Any]) -> Optional[TechnicalCaptureResult]:
    policy = load_technical_capture_policy()
    markers = list(policy.get("technical_status_markers") or []) + list(
        policy.get("capture_intent_markers") or []
    )
    if not _phrase_match(query, markers):
        return None
    cap = technical_capture_status(session_state)
    ux = (load_chat_copilot_ux_messages().get("technical_capture") or {})
    if cap.get("capture_complete"):
        status = str(ux.get("status_complete") or "")
        cta = str(ux.get("cta_generate") or "")
    else:
        status = str(ux.get("status_pending_summary") or "").format(
            missing=int(cap.get("missing") or 0),
            filled=int(cap.get("filled") or 0),
            total=int(cap.get("total") or 0),
        )
        cta = str(ux.get("cta_capture") or "")
    msg = format_gate5_message(
        status=status,
        detail=build_technical_discovery_message(session_state).split("\n", 1)[-1][:1200],
        cta=cta,
    )
    return TechnicalCaptureResult(
        handled=True,
        respuesta=msg,
        tipo="technical_capture_status",
        technical_capture_v1=build_technical_capture_v1_api_payload(session_state),
    )


def _try_handle_natural_capture(
    query: str,
    session_state: Dict[str, Any],
) -> Optional[TechnicalCaptureResult]:
    parsed = parse_technical_capture_phrase(query)
    if not parsed:
        return None
    slot_kind, value, prefix = parsed
    label = prefix.replace("_", " ").title()
    concept_key = stable_concept_key(label, slot_kind)
    for slot in build_technical_slot_inventory(session_state):
        if str(slot.get("slot_kind") or "") == slot_kind:
            concept_key = str(slot.get("concept_key") or concept_key)
            label = str(slot.get("label") or label)
            capture_mode = str(slot.get("capture_mode") or "chat_natural")
            break
    else:
        capture_mode = "chat_natural"
    updates = _apply_capture_value(
        session_state,
        concept_key=concept_key,
        label=label,
        slot_kind=slot_kind,
        capture_mode=capture_mode,
        value_text=value,
        original_phrase=query,
    )
    merged = {**session_state, **updates}
    nxt = _next_pending_slot(merged)
    msg = build_technical_capture_confirmation_message(
        session_state=merged,
        label=label,
        value_text=value,
        next_label=str(nxt.get("label")) if nxt else None,
    )
    return TechnicalCaptureResult(
        handled=True,
        respuesta=msg,
        tipo="technical_capture",
        session_updates=updates,
        technical_capture_v1=build_technical_capture_v1_api_payload(merged),
    )


def try_handle_technical_capture(
    *,
    query: str,
    session_state: Dict[str, Any],
) -> Optional[TechnicalCaptureResult]:
    q = str(query or "").strip()
    if not q or q.startswith("CMD_"):
        return None
    for handler in (
        lambda: _try_handle_defer(q),
        lambda: _try_handle_dual_status(q, session_state),
        lambda: _try_handle_technical_status(q, session_state),
        lambda: _try_handle_natural_capture(q, session_state),
    ):
        result = handler()
        if result is not None:
            result.respuesta = sanitize_user_visible_text(result.respuesta)
            if result.technical_capture_v1 is None and result.session_updates:
                merged = {**session_state, **result.session_updates}
                result.technical_capture_v1 = build_technical_capture_v1_api_payload(merged)
            return result
    return None


async def apply_technical_capture_to_agent_output(
    result: TechnicalCaptureResult,
    *,
    agent: Any,
    session_id: str,
    user_query: str,
    session_state: Dict[str, Any],
    correlation_id: str,
    activity_state: str = "active",
) -> Any:
    if not result.handled:
        return None
    if result.session_updates:
        await agent.context_manager.memory.save_session(session_id, result.session_updates)
    if result.respuesta:
        extra: Dict[str, Any] = {}
        if result.technical_capture_v1:
            extra["technical_capture_v1"] = result.technical_capture_v1
        return agent._format_response(
            session_id=session_id,
            correlation_id=correlation_id,
            respuesta=result.respuesta,
            confianza="Alta",
            tipo=result.tipo,
            activity_state=activity_state,
            **extra,
        )
    return None
