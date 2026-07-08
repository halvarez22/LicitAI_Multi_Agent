"""
Orquestador HRU del copiloto económico conversacional (F1).

Centraliza parseo, merge canónico, confirmación, conflictos y respuestas Gate 5.
Sin hardcode por licitación — reglas en ``economic_capture_policy.json``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.chat_gate5_formatter import format_gate5_message
from app.services.chat_stop_reason_map import sanitize_user_visible_text
from app.services.economic_canonical_v1 import (
    build_economic_capture_v1_api_payload,
    sync_economic_canonical_v1,
)
from app.services.economic_capture_matrix_service import economic_capture_status
from app.services.expediente_guided_service import economic_capture_honest_status
from app.services.economic_calculation_service import (
    build_generar_economica_incomplete_message,
    build_price_capture_confirmation_message,
    economic_capture_cta,
    load_chat_copilot_ux_messages,
)

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "economic_capture_policy.json"
)

_ECON_PENDING_TYPES = frozenset(
    {"economic_price", "economic_price_matrix", "economic_validation_blocking"}
)


@dataclass
class EconomicCaptureResult:
    """Resultado de ``try_handle_economic_capture``."""

    handled: bool = False
    respuesta: str = ""
    tipo: str = "info"
    session_updates: Dict[str, Any] = field(default_factory=dict)
    economic_capture_v1: Optional[Dict[str, Any]] = None
    delegate_to_agent: Optional[str] = None
    delegate_payload: Dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_economic_capture_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _norm(text: str) -> str:
    raw = (text or "").strip().lower()
    nk = unicodedata.normalize("NFD", raw)
    t = "".join(c for c in nk if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def _phrase_match(query: str, phrases: List[str]) -> bool:
    q = _norm(query)
    return any(_norm(p) in q for p in (phrases or []))


def _economic_pending(pending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        q
        for q in (pending or [])
        if isinstance(q, dict) and str(q.get("type") or "") in _ECON_PENDING_TYPES
    ]


@dataclass
class GenerarEconomicaGateResult:
    """Resultado del gate F8 para intención GENERAR_ECONOMICA."""

    should_block: bool = False
    message: str = ""
    capture_complete: bool = False
    materializing_lead: str = ""


def gate_generar_economica_intent(session_state: Dict[str, Any]) -> GenerarEconomicaGateResult:
    """
    Bloquea materialización si faltan precios; permite continuar si snapshot completo.
    """
    cap = economic_capture_honest_status(session_state)
    complete = bool(cap.get("capture_complete"))
    ux = (load_chat_copilot_ux_messages().get("economic_capture") or {})
    materializing = str(ux.get("generar_materializing") or "")
    if complete:
        return GenerarEconomicaGateResult(
            should_block=False,
            capture_complete=True,
            materializing_lead=materializing,
        )
    total = int(cap.get("total") or 0)
    if total <= 0 and int(cap.get("filled") or 0) <= 0:
        return GenerarEconomicaGateResult(should_block=False, capture_complete=False)
    return GenerarEconomicaGateResult(
        should_block=True,
        message=build_generar_economica_incomplete_message(session_state),
        capture_complete=False,
    )


def _build_economic_status_message(session_state: Dict[str, Any]) -> str:
    cap = economic_capture_honest_status(session_state)
    ux = (load_chat_copilot_ux_messages().get("economic_capture") or {})
    name = str(session_state.get("name") or "esta licitación")
    missing = int(cap.get("missing") or 0)
    filled = int(cap.get("filled") or 0)
    total = int(cap.get("total") or 0)
    if cap.get("capture_complete"):
        status = f"{ux.get('status_complete', 'Cotización completa.')} — **{name}**."
        detail = f"Registré **{filled}** precio(s)."
        cta = economic_capture_cta(capture_complete=True)
    elif total > 0:
        status = ux.get("status_pending", "").format(missing=missing, filled=filled, total=total)
        status = f"{status} — **{name}**."
        detail = ""
        cta = economic_capture_cta(capture_complete=False)
    else:
        status = f"Aún no hay matriz de precios detectada para **{name}**."
        detail = "Cuando el análisis indexe anexos económicos, te mostraré qué capturar."
        cta = economic_capture_cta(capture_complete=False)
    return format_gate5_message(status=status, detail=detail, cta=cta)


def _try_handle_defer(query: str) -> Optional[EconomicCaptureResult]:
    policy = load_economic_capture_policy()
    if not _phrase_match(query, list(policy.get("defer_capture_phrases") or [])):
        return None
    msg = format_gate5_message(
        status="Entendido — dejamos los precios para la **propuesta económica**.",
        detail=str(
            (load_chat_copilot_ux_messages().get("economic_capture") or {}).get(
                "defer_detail",
                "Cuando quieras capturarlos, escríbeme aquí en el chat.",
            )
        ),
        cta=economic_capture_cta(capture_complete=False),
    )
    return EconomicCaptureResult(handled=True, respuesta=msg, tipo="economic_deferred")


def _try_handle_conflict_resolution(
    query: str,
    session_state: Dict[str, Any],
) -> Optional[EconomicCaptureResult]:
    conflict = session_state.get("_economic_source_conflict")
    if not isinstance(conflict, dict):
        return None
    policy = load_economic_capture_policy()
    phrases = policy.get("conflict_resolution_phrases") or {}
    prefer_excel = _phrase_match(query, list(phrases.get("prefer_excel") or []))
    prefer_chat = _phrase_match(query, list(phrases.get("prefer_chat") or []))
    if not prefer_excel and not prefer_chat:
        return None

    field_key = str(conflict.get("concept_key") or conflict.get("field") or "")
    excel_val = conflict.get("excel_value")
    chat_val = conflict.get("chat_value")
    chosen = excel_val if prefer_excel else chat_val
    channel = "user_excel" if prefer_excel else "user_chat"

    inputs = dict(session_state.get("economic_user_inputs") or {})
    if field_key and chosen is not None:
        inputs[field_key] = chosen

    overrides = dict(session_state.get("economic_user_overrides") or {})
    if field_key:
        overrides[field_key] = {"source": channel, "original_phrase": str(query or "")[:240]}

    merged_state = {
        **session_state,
        "economic_user_inputs": inputs,
        "economic_user_overrides": overrides,
        "_economic_source_conflict": None,
    }
    updates = {
        "economic_user_inputs": inputs,
        "economic_user_overrides": overrides,
        "_economic_source_conflict": None,
        **sync_economic_canonical_v1(merged_state),
    }
    label = str(conflict.get("label") or field_key or "precio")
    merged_for_msg = {**merged_state, **updates}
    try:
        chosen_num = float(str(chosen).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        chosen_num = chosen
    msg = build_price_capture_confirmation_message(
        session_state=merged_for_msg,
        label=label,
        amount_mxn=chosen_num,
    )
    return EconomicCaptureResult(
        handled=True,
        respuesta=msg,
        tipo="data_saved",
        session_updates=updates,
        economic_capture_v1=build_economic_capture_v1_api_payload({**merged_state, **updates}),
    )


def _try_handle_confirm_pending(
    query: str,
    session_state: Dict[str, Any],
) -> Optional[EconomicCaptureResult]:
    confirm = session_state.get("_price_confirm_pending")
    if not isinstance(confirm, dict) or not confirm.get("value"):
        return None
    policy = load_economic_capture_policy()
    low = _norm(query)
    affirm = {_norm(x) for x in (policy.get("confirm_affirmative") or [])}
    if low not in affirm:
        return None
    return EconomicCaptureResult(
        handled=True,
        respuesta="",
        tipo="pending_confirm_apply",
        delegate_to_agent="apply_price_confirm",
        delegate_payload={
            "field": str(confirm.get("field") or ""),
            "value": str(confirm.get("value") or ""),
            "label": str(confirm.get("label") or ""),
        },
        session_updates={"_price_confirm_pending": None},
    )


def _try_handle_economic_status_query(
    query: str,
    session_state: Dict[str, Any],
) -> Optional[EconomicCaptureResult]:
    policy = load_economic_capture_policy()
    if not _phrase_match(query, list(policy.get("economic_status_markers") or [])):
        return None
    msg = _build_economic_status_message(session_state)
    return EconomicCaptureResult(
        handled=True,
        respuesta=msg,
        tipo="economic_capture_status",
        economic_capture_v1=build_economic_capture_v1_api_payload(session_state),
    )


def detect_economic_source_conflict(
    *,
    concept_key: str,
    label: str,
    chat_value: float,
    excel_value: float,
    tolerance: float = 0.02,
) -> Optional[Dict[str, Any]]:
    """Detecta conflicto chat vs Excel por concepto (HRU universal)."""
    if abs(float(chat_value) - float(excel_value)) <= tolerance:
        return None
    return {
        "concept_key": concept_key,
        "field": concept_key,
        "label": label,
        "chat_value": chat_value,
        "excel_value": excel_value,
    }


def try_handle_economic_capture(
    *,
    query: str,
    session_state: Dict[str, Any],
    pending_questions: Optional[List[Dict[str, Any]]] = None,
) -> Optional[EconomicCaptureResult]:
    """
    Intenta resolver captura/confirmación/conflictos sin RAG.

    Returns:
        ``EconomicCaptureResult`` si manejó el turno; ``None`` para continuar pipeline.
    """
    q = str(query or "").strip()
    if not q or q.startswith("CMD_"):
        return None

    for handler in (
        lambda: _try_handle_confirm_pending(q, session_state),
        lambda: _try_handle_conflict_resolution(q, session_state),
        lambda: _try_handle_defer(q),
        lambda: _try_handle_economic_status_query(q, session_state),
    ):
        result = handler()
        if result is not None:
            result.respuesta = sanitize_user_visible_text(result.respuesta)
            if result.economic_capture_v1 is None and result.session_updates:
                merged = {**session_state, **result.session_updates}
                result.economic_capture_v1 = build_economic_capture_v1_api_payload(merged)
            return result

    eco_pending = _economic_pending(list(pending_questions or []))
    if eco_pending and _looks_like_tsv_bulk(q):
        return EconomicCaptureResult(
            handled=True,
            respuesta="",
            tipo="tsv_bulk_delegate",
            delegate_to_agent="tsv_bulk",
        )

    return None


def _looks_like_tsv_bulk(text: str) -> bool:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    tab_lines = sum(1 for ln in lines if "\t" in ln)
    return tab_lines >= 2


async def apply_economic_capture_to_agent_output(
    result: EconomicCaptureResult,
    *,
    agent: Any,
    session_id: str,
    company_id: str,
    user_query: str,
    session_state: Dict[str, Any],
    pending_questions: List[Dict[str, Any]],
    current_idx: int,
    correlation_id: str,
    activity_state: str = "active",
) -> Any:
    """
    Completa delegaciones que requieren métodos del agente chatbot.
    """
    if not result.handled:
        return None

    if result.session_updates:
        await agent.context_manager.memory.save_session(session_id, result.session_updates)
        session_state = {**session_state, **result.session_updates}

    if result.delegate_to_agent == "apply_price_confirm":
        payload = result.delegate_payload
        field_key = str(payload.get("field") or "")
        pending = list(pending_questions or [])
        current_q = next(
            (q for q in pending if str(q.get("field") or "") == field_key),
            pending[current_idx] if pending else {},
        )
        return await agent._apply_saved_pending_value(
            session_id=session_id,
            user_input_for_history=user_query,
            company_id=company_id,
            current_q=current_q,
            pending=pending,
            current_idx=current_idx,
            session_state=session_state,
            extracted_value=str(payload.get("value") or ""),
            correlation_id=correlation_id,
            saved_via="chat_confirm",
        )

    if result.delegate_to_agent == "tsv_bulk":
        bulk = await agent._try_tsv_bulk_economic_prices(
            session_id, user_query, company_id, session_state, correlation_id
        )
        if bulk is not None:
            data = dict(bulk.data or {})
            data["economic_capture_v1"] = build_economic_capture_v1_api_payload(session_state)
            bulk.data = data
        return bulk

    if result.respuesta:
        extra: Dict[str, Any] = {}
        if result.economic_capture_v1:
            extra["economic_capture_v1"] = result.economic_capture_v1
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
