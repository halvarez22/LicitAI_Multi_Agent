"""
Router HRU de misión del expediente — prioriza el siguiente paso de negocio en chat.

Orden (sin relajar gates):
  1. Captura económica (cotización en chat)
  2. Captura técnica (slots en chat)
  3. Confirmación plan documental (quality gate humanizado)
  4. Listo para generar (técnica / económica / dual)

Fuente de copy: ``document_quality_ux_messages.json`` + copilotos F8/F9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.chat_gate5_formatter import format_gate5_message
from app.services.document_quality_ux import (
    build_document_quality_gate_message,
    load_document_quality_ux_messages,
)


@dataclass
class ExpedienteMission:
    """Siguiente misión conversacional para el licitante."""

    mission_id: str
    priority: int
    title: str
    message: str
    cta: str = ""
    present_on_greeting: bool = True
    provenance: Dict[str, Any] = field(default_factory=dict)


def _mission_tpl(key: str) -> str:
    raw = load_document_quality_ux_messages().get("expediente_mission") or {}
    return str(raw.get(key) or "")


def _session_name(session_state: Dict[str, Any]) -> str:
    return str(session_state.get("name") or "").strip() or "esta licitación"


def _has_quality_gate_pending(session_state: Dict[str, Any]) -> bool:
    if isinstance(session_state.get("last_document_quality_waiting_hints"), dict):
        return True
    for q in session_state.get("pending_questions") or []:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "")
        field_key = str(q.get("field") or "")
        if qtype in ("document_quality_gate_blocking", "quality_validation_blocking"):
            if field_key in ("", "document_quality_gate", "quality.classification.review"):
                return True
        if field_key == "document_quality_gate":
            return True
    return False


def _is_price_source_pending_question(q: Dict[str, Any]) -> bool:
    """True si el pendiente pide catálogo/fuente de precios antes de capturar importes."""
    if not isinstance(q, dict):
        return False
    if str(q.get("type") or "") != "economic_validation_blocking":
        return False
    if str(q.get("input_mode") or "").strip().lower() == "price_source":
        return True
    if str(q.get("field") or "").strip() == "economic_price_source":
        return True
    items = q.get("blocking_items") if isinstance(q.get("blocking_items"), list) else []
    return any(
        str(it.get("requested_input") or "").strip().lower() == "price_source" for it in items
    )


def _has_price_source_pending(session_state: Dict[str, Any]) -> bool:
    for q in session_state.get("pending_questions") or []:
        if _is_price_source_pending_question(q):
            return True
    return False


def _price_source_reference_label(session_state: Dict[str, Any]) -> str:
    import re

    for q in session_state.get("pending_questions") or []:
        if not _is_price_source_pending_question(q):
            continue
        items = q.get("blocking_items") if isinstance(q.get("blocking_items"), list) else []
        if items:
            lbl = str(items[0].get("concepto_label") or "").strip()
            if lbl:
                return lbl
        qtxt = str(q.get("question") or "")
        match = re.search(r"\*\*(.+?)\*\*", qtxt)
        if match:
            return match.group(1).strip()
    ref = _first_economic_label(session_state)
    if ref and ref != "los servicios de la licitación":
        return ref
    return "el formato o anexo económico de las bases"


def _economic_mission_needed(session_state: Dict[str, Any]) -> bool:
    from app.services.economic_capture_matrix_service import (
        count_filled_price_inputs,
        economic_capture_status,
    )
    from app.services.expediente_mission_policy import session_signals_service_pricing

    if _has_price_source_pending(session_state):
        return True

    cap = economic_capture_status(session_state)
    if cap.get("capture_complete"):
        return False
    if int(cap.get("missing") or 0) > 0:
        return True
    if int(cap.get("pending_economic") or 0) > 0:
        return True
    line_items = session_state.get("session_line_items") or []
    inputs = session_state.get("economic_user_inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    price_filled = count_filled_price_inputs(inputs)
    if isinstance(line_items, list) and line_items and price_filled < len(line_items):
        return True
    if session_state.get("economic_post_analysis_hook_pending"):
        return True
    if not session_signals_service_pricing(session_state):
        return False
    total = int(cap.get("total") or 0)
    if total > 0 and price_filled < total:
        return True
    return price_filled <= 0


def _technical_mission_needed(session_state: Dict[str, Any]) -> bool:
    from app.services.technical_slot_mapper import technical_capture_status

    cap = technical_capture_status(session_state)
    if cap.get("capture_complete"):
        return False
    total = int(cap.get("total") or 0)
    if total <= 0:
        return False
    if session_state.get("technical_post_analysis_hook_pending"):
        return True
    return int(cap.get("missing") or 0) > 0


def _first_economic_label(session_state: Dict[str, Any]) -> str:
    from app.services.economic_capture_matrix_service import economic_capture_status

    cap = economic_capture_status(session_state)
    nxt = str(cap.get("next_label") or cap.get("next_field_label") or "").strip()
    if nxt:
        return nxt
    for row in session_state.get("session_line_items") or []:
        if not isinstance(row, dict):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        label = str(
            extra.get("location_label")
            or row.get("concepto_raw")
            or row.get("label")
            or ""
        ).strip()
        if label:
            return label
    blocks = session_state.get("capture_matrix_blocks") or []
    if blocks and isinstance(blocks[0], dict):
        for row in blocks[0].get("matrix_rows") or []:
            if isinstance(row, dict):
                lbl = str(row.get("label") or row.get("field") or "").strip()
                if lbl:
                    return lbl
    return "los servicios de la licitación"


def _missing_technical_labels(session_state: Dict[str, Any], *, limit: int = 3) -> str:
    from app.services.technical_capture_ux import list_missing_technical_labels

    labels = list_missing_technical_labels(session_state, limit=limit)
    if not labels:
        return "metodología y personal mínimo"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" y {labels[-1]}"


def _service_hint(session_state: Dict[str, Any]) -> str:
    from app.services.expediente_mission_policy import (
        load_expediente_mission_policy,
        resolve_service_hint_from_session_name,
    )

    hinted = resolve_service_hint_from_session_name(session_state)
    if hinted:
        return hinted
    label = _first_economic_label(session_state)
    if label and label != "los servicios de la licitación":
        return label
    facts_labels: List[str] = []
    try:
        from app.services.chat_expediente_bootstrap_service import collect_expediente_bootstrap_facts

        facts = collect_expediente_bootstrap_facts(session_state)
        facts_labels = list(facts.generate_labels[:2])
    except Exception:
        pass
    if facts_labels:
        return facts_labels[0]
    cfg = load_expediente_mission_policy().get("economic_first") or {}
    return str(cfg.get("default_service_hint") or "los servicios licitados")


def _build_economic_mission_message(session_state: Dict[str, Any], session_name: str) -> str:
    next_label = _first_economic_label(session_state)
    service_hint = _service_hint(session_state)
    has_specific_label = next_label and next_label != "los servicios de la licitación"
    if has_specific_label:
        body_tpl = _mission_tpl("economic_capture_body")
        body = body_tpl.format(
            session_name=session_name,
            service_hint=service_hint,
            next_label=next_label,
        )
    else:
        body = _mission_tpl("economic_capture_body_no_label").format(
            session_name=session_name,
            service_hint=service_hint,
        )
    return format_gate5_message(
        status=_mission_tpl("economic_capture_lead").format(session_name=session_name),
        detail=body,
        cta=_mission_tpl("economic_capture_cta"),
    )


def _build_service_dual_opening_message(session_state: Dict[str, Any], session_name: str) -> str:
    """Apertura profesional servicios: cotización primero, técnica en segundo plano."""
    next_label = _first_economic_label(session_state)
    service_hint = _service_hint(session_state)
    missing = _missing_technical_labels(session_state)
    has_specific_label = next_label and next_label != "los servicios de la licitación"
    if _has_price_source_pending(session_state):
        body = _mission_tpl("service_dual_body_price_source").format(
            price_ref_label=_price_source_reference_label(session_state),
            missing_labels=missing,
        )
    elif has_specific_label:
        body = _mission_tpl("service_dual_body_with_label").format(
            session_name=session_name,
            service_hint=service_hint,
            next_label=next_label,
            missing_labels=missing,
        )
    else:
        body = _mission_tpl("service_dual_body_no_label").format(
            session_name=session_name,
            service_hint=service_hint,
            missing_labels=missing,
        )
    return format_gate5_message(
        status=_mission_tpl("service_dual_lead").format(session_name=session_name),
        detail=body,
        cta=_mission_tpl("service_dual_cta"),
    )


def resolve_expediente_mission(session_state: Dict[str, Any]) -> Optional[ExpedienteMission]:
    """
    Determina la misión principal del chat según estado canónico de sesión.
    """
    if not isinstance(session_state, dict):
        return None
    session_name = _session_name(session_state)
    eco_needed = _economic_mission_needed(session_state)
    tech_needed = _technical_mission_needed(session_state)

    from app.services.expediente_mission_policy import session_signals_service_pricing

    if tech_needed and session_signals_service_pricing(session_state) and (
        eco_needed or _has_price_source_pending(session_state)
    ):
        msg = _build_service_dual_opening_message(session_state, session_name)
        return ExpedienteMission(
            mission_id="service_dual_opening",
            priority=5,
            title="Cotización pendiente",
            message=msg,
            cta=_mission_tpl("service_dual_cta"),
            provenance={
                "source": "expediente_mission_router",
                "track": "economic+technical",
                "opening": "service_dual",
            },
        )

    if eco_needed:
        msg = _build_economic_mission_message(session_state, session_name)
        return ExpedienteMission(
            mission_id="economic_capture",
            priority=10,
            title="Cotización pendiente",
            message=msg,
            cta=_mission_tpl("economic_capture_cta"),
            provenance={"source": "expediente_mission_router", "track": "economic"},
        )

    if tech_needed:
        missing = _missing_technical_labels(session_state)
        msg = format_gate5_message(
            status=_mission_tpl("technical_capture_lead").format(session_name=session_name),
            detail=_mission_tpl("technical_capture_body").format(
                session_name=session_name,
                missing_labels=missing,
            ),
            cta=_mission_tpl("technical_capture_cta"),
        )
        return ExpedienteMission(
            mission_id="technical_capture",
            priority=20,
            title="Propuesta técnica pendiente",
            message=msg,
            cta=_mission_tpl("technical_capture_cta"),
            provenance={"source": "expediente_mission_router", "track": "technical"},
        )

    if _has_quality_gate_pending(session_state):
        hint = session_state.get("last_document_quality_waiting_hints")
        gate: Dict[str, Any] = {"reason": "default", "metrics": {}}
        if isinstance(hint, dict):
            gate["reason"] = str(hint.get("reason") or "default")
            if isinstance(hint.get("metrics"), dict):
                gate["metrics"] = hint["metrics"]
        msg = build_document_quality_gate_message(gate=gate, session_state=session_state)
        return ExpedienteMission(
            mission_id="quality_classification",
            priority=30,
            title="Confirmar documentos",
            message=msg,
            provenance={"source": "document_quality_gate", "reason": gate.get("reason")},
        )

    from app.services.economic_capture_matrix_service import economic_capture_status
    from app.services.technical_slot_mapper import technical_capture_status

    eco = economic_capture_status(session_state)
    tech = technical_capture_status(session_state)
    eco_ok = bool(eco.get("capture_complete")) or int(eco.get("total") or 0) == 0
    tech_ok = bool(tech.get("capture_complete")) or int(tech.get("total") or 0) == 0

    if eco_ok and tech_ok and session_state.get("tasks_completed"):
        if int(eco.get("total") or 0) > 0 and int(tech.get("total") or 0) > 0:
            mid = "ready_dual"
            cta = _mission_tpl("ready_dual_cta")
            body = _mission_tpl("ready_dual_body")
        elif int(eco.get("total") or 0) > 0:
            mid = "ready_economic"
            cta = _mission_tpl("ready_economic_cta")
            body = "La cotización está lista en el chat."
        elif int(tech.get("total") or 0) > 0:
            mid = "ready_technical"
            cta = _mission_tpl("ready_technical_cta")
            body = "Los datos técnicos están listos en el chat."
        else:
            return None
        msg = format_gate5_message(
            status=_mission_tpl("ready_dual_lead").format(session_name=session_name),
            detail=body,
            cta=cta,
        )
        return ExpedienteMission(
            mission_id=mid,
            priority=90,
            title="Listo para generar",
            message=msg,
            cta=cta,
            present_on_greeting=True,
            provenance={"source": "expediente_mission_router", "track": "generation"},
        )

    return None


def is_greeting_or_opening(user_query: str) -> bool:
    q = str(user_query or "").strip().lower()
    if not q:
        return True
    return q in {
        "hola",
        "hi",
        "hello",
        "buenas",
        "buenas tardes",
        "buenas noches",
        "buenos dias",
        "buenos días",
        "hey",
        "buen dia",
        "buen día",
    }
