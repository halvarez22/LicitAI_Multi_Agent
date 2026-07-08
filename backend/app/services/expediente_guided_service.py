"""
HRU P0 — estado del expediente guiado (pasos, CTA único, captura honesta).

Fuentes: ``expediente_guided_policy.json``, ``expediente_guided_ux_messages.json``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config.settings import settings
from app.services.economic_capture_matrix_service import economic_capture_status

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "expediente_guided_policy.json"
_UX_PATH = Path(__file__).resolve().parents[1] / "contracts" / "expediente_guided_ux_messages.json"

_QUALITY_PENDING_TYPES = frozenset(
    {"document_quality_gate_blocking", "quality_validation_blocking"}
)


@lru_cache(maxsize=1)
def load_expediente_guided_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_expediente_guided_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_expediente_guided_policy().get("policy_version") or "")


def expediente_guided_enabled() -> bool:
    return bool(getattr(settings, "EXPEDIENTE_GUIDED_ENABLED", True))


def _economic_pending_types() -> frozenset:
    raw = load_expediente_guided_policy().get("economic_pending_types") or []
    return frozenset(str(x) for x in raw)


def _tasks_completed(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [t for t in (session_state.get("tasks_completed") or []) if isinstance(t, dict)]


def _has_analysis_task(session_state: Dict[str, Any], *, analysis_done_hint: bool = False) -> bool:
    if analysis_done_hint:
        return True
    task = str(load_expediente_guided_policy().get("analysis_task") or "stage_completed:analysis")
    return any(str(t.get("task") or "") == task for t in _tasks_completed(session_state))


def _economic_validated(session_state: Dict[str, Any]) -> bool:
    guided = session_state.get("expediente_guided_v1")
    if isinstance(guided, dict) and guided.get("economic_validated_at"):
        return True
    for t in _tasks_completed(session_state):
        if str(t.get("task") or "") in ("economic_proposal", "stage_completed:economic"):
            res = t.get("result") if isinstance(t.get("result"), dict) else {}
            if str(res.get("status") or "").lower() in ("success", "complete", "ok"):
                return True
    return False


def _quality_pending(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
  types = _QUALITY_PENDING_TYPES | frozenset(
      load_expediente_guided_policy().get("quality_pending_types") or []
  )
  return [
      q
      for q in (session_state.get("pending_questions") or [])
      if isinstance(q, dict) and str(q.get("type") or "") in types
  ]


def _document_plan_ready(session_state: Dict[str, Any]) -> bool:
    if _quality_pending(session_state):
        return False
    gate = session_state.get("last_document_quality_gate")
    if isinstance(gate, dict) and gate.get("block") is True:
        reason = str(gate.get("reason") or "")
        if reason in ("no_actionable_generate_items", "cross_tender_reference"):
            return False
    gen = session_state.get("generation_state")
    if isinstance(gen, dict):
        jobs = gen.get("jobs") or []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            if str(job.get("id") or "") == "formats" and str(job.get("status") or "") == "blocked":
                return False
    return True


def _motor_pending_economic(session_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    types = _economic_pending_types()
    return [
        q
        for q in (session_state.get("pending_questions") or [])
        if isinstance(q, dict) and str(q.get("type") or "") in types
    ]


def _humanize_pending_label(q: Dict[str, Any]) -> str:
    lbl = str(q.get("label") or "").strip()
    for pfx in (
        "Precio de: ",
        "PU oferta económica — ",
        "Precio (sin IVA): ",
        "Precio unitario: ",
    ):
        if lbl.startswith(pfx):
            lbl = lbl[len(pfx) :].strip()
    return lbl or str(q.get("field") or "partida")


def economic_capture_honest_status(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Captura económica con señales honestas matriz vs motor HITL.
    """
    policy = load_expediente_guided_policy()
    honesty = policy.get("capture_honesty") or {}
    tolerance = int(honesty.get("matrix_complete_tolerance") or 0)
    require_pending_zero = bool(honesty.get("require_pending_economic_zero", True))

    cap = economic_capture_status(session_state)
    motor = _motor_pending_economic(session_state)
    motor_n = len(motor)
    filled = int(cap.get("filled") or 0)
    total = int(cap.get("total") or 0)
    matrix_filled = filled >= max(0, total - tolerance) if total > 0 else filled > 0
    matrix_complete = total > 0 and filled >= total - tolerance
    motor_complete = motor_n == 0 if require_pending_zero else True
    capture_complete = matrix_complete and motor_complete and (
        not require_pending_zero or motor_n == 0
    )

    first_motor = _humanize_pending_label(motor[0]) if motor else ""
    return {
        **cap,
        "filled": filled,
        "total": total,
        "missing": max(0, total - filled),
        "motor_pending_count": motor_n,
        "motor_pending_label": first_motor,
        "matrix_complete": matrix_complete,
        "motor_complete": motor_complete,
        "capture_complete": capture_complete,
    }


def format_honest_capture_summary(
    status: Dict[str, Any],
    *,
    economic_validated: bool = False,
) -> str:
    """Mensaje UX honesto para matriz + motor."""
    ux = (load_expediente_guided_ux_messages().get("capture_honesty") or {})
    filled = int(status.get("filled") or 0)
    total = int(status.get("total") or 0)
    motor_n = int(status.get("motor_pending_count") or 0)
    motor_label = str(status.get("motor_pending_label") or "partida pendiente")

    if total <= 0 and motor_n <= 0:
        return "Aún no hay filas de precio detectadas en la matriz."
    if motor_n > 0 and filled >= total and total > 0:
        tpl = ux.get("matrix_complete_motor_pending") or (
            "Matriz {filled}/{total} — falta {motor_pending} partida del motor ({motor_label})."
        )
        return tpl.format(
            filled=filled,
            total=total,
            motor_pending=motor_n,
            motor_label=motor_label,
        )
    if status.get("capture_complete"):
        key = "matrix_complete_validated" if economic_validated else "matrix_complete_ready_validate"
        tpl = ux.get(key) or "Cotización {filled}/{total}."
        return tpl.format(filled=filled, total=total)
    missing = max(0, total - filled)
    tpl = ux.get("matrix_incomplete") or "Capturaste {filled} de {total}."
    return tpl.format(filled=filled, total=total, missing=missing)


def split_economic_price_reply(raw: str) -> Tuple[str, str]:
    """Separa precio numérico y cola opcional (ej. 5800; 24x24)."""
    cfg = load_expediente_guided_policy().get("economic_price_reply") or {}
    s = (raw or "").strip().replace(",", "")
    if cfg.get("schedule_split_semicolon") and ";" in s:
        a, b = s.split(";", 1)
        return a.strip(), b.strip()
    token_re = str(cfg.get("schedule_token_regex") or "[xX×]")
    m = re.match(rf"^(-?\d+(?:\.\d+)?)\s+(.{{{2},80}})$", s)
    if m and re.search(token_re, m.group(2)):
        return m.group(1).strip(), m.group(2).strip()
    return s, ""


def looks_like_economic_price_reply(query: str) -> bool:
    """True si el texto parece respuesta de precio unitario (+ esquema horario opcional)."""
    if not (query or "").strip():
        return False
    cfg = load_expediente_guided_policy().get("economic_price_reply") or {}
    work, tail = split_economic_price_reply(query)
    num_re = str(cfg.get("numeric_strict_regex") or r"^-?\d+(?:\.\d+)?$")
    work_clean = work.replace("$", "").replace("mxn", "").replace("MXN", "").strip()
    if re.match(num_re, work_clean):
        return True
    token_re = str(cfg.get("schedule_token_regex") or "[xX×]")
    if tail and re.search(token_re, tail) and re.match(num_re, work_clean):
        return True
    return False


def find_economic_price_pending_index(
    pending: List[Dict[str, Any]],
    user_query: str,
    session_state: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """
    Índice del pendiente ``economic_price`` más adecuado para preempt routing.
    """
    cfg = load_expediente_guided_policy().get("preempt_price_routing") or {}
    if not cfg.get("enabled", True):
        return None
    types = _economic_pending_types()
    candidates: List[Tuple[int, Dict[str, Any]]] = [
        (i, q)
        for i, q in enumerate(pending or [])
        if isinstance(q, dict) and str(q.get("type") or "") == "economic_price"
    ]
    if not candidates:
        return None

    _, schedule_tail = split_economic_price_reply(user_query)
    prefer_guard = bool(cfg.get("prefer_guard_schedule_pending_when_schedule_in_reply", True))
    if prefer_guard and schedule_tail:
        for i, q in candidates:
            if q.get("capture_guard_schedule"):
                return i

    st = session_state or {}
    line_items = st.get("session_line_items") or []
    for i, q in candidates:
        concept = _humanize_pending_label(q).lower()
        if concept and concept in (user_query or "").lower():
            return i
    for i, q in candidates:
        field = str(q.get("field") or "")
        for row in line_items:
            if not isinstance(row, dict):
                continue
            if str(row.get("field") or row.get("id") or "") == field:
                return i
    return candidates[0][0]


def resolve_expediente_guided_state(
    session_state: Dict[str, Any],
    *,
    analysis_done_hint: bool = False,
    company_profile: Optional[Dict[str, Any]] = None,
    company_exists: Optional[bool] = None,
    session_output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Payload canónico para UI: paso actual, barra de progreso y CTA primario.
    """
    policy = load_expediente_guided_policy()
    ux = load_expediente_guided_ux_messages()
    step_order = list(policy.get("step_order") or [])
    steps_ux = ux.get("steps") or {}
    labels = policy.get("panel_button_labels") or {}
    hints = policy.get("generation_hints") or {}

    analysis_done = _has_analysis_task(session_state, analysis_done_hint=analysis_done_hint)

    readiness: Optional[Dict[str, Any]] = None
    use_readiness = False
    try:
        from app.services.expediente_readiness_service import readiness_gates_enabled, resolve_expediente_readiness

        use_readiness = readiness_gates_enabled()
        if use_readiness:
            readiness = resolve_expediente_readiness(
                session_state,
                company_profile=company_profile,
                company_exists=company_exists,
                session_output_path=session_output_path,
            )
    except Exception:
        use_readiness = False

    cap = economic_capture_honest_status(session_state)
    if use_readiness and readiness:
        capture = readiness.get("capture") if isinstance(readiness.get("capture"), dict) else {}
        cap = {
            **cap,
            "capture_complete": bool(capture.get("ready")),
            "filled": capture.get("matrix_filled", cap.get("filled")),
            "total": capture.get("matrix_total", cap.get("total")),
        }
        eco_validated = bool((readiness.get("generation") or {}).get("economic_writer_allowed"))
    else:
        eco_validated = _economic_validated(session_state)

    plan_ready = _document_plan_ready(session_state)

    current = "materializar"
    if not analysis_done:
        current = "bases"
    elif not cap.get("capture_complete"):
        current = "cotizacion"
    elif not eco_validated:
        current = "validar_economica"
    elif not plan_ready:
        current = "plan_documentos"

    current_idx = step_order.index(current) if current in step_order else 0
    steps_out: List[Dict[str, Any]] = []
    for i, sid in enumerate(step_order):
        meta = steps_ux.get(sid) if isinstance(steps_ux.get(sid), dict) else {}
        status = "future"
        if i < current_idx:
            status = "done"
        elif sid == current:
            status = "current"
        steps_out.append(
            {
                "id": sid,
                "label": str(meta.get("label") or sid),
                "hint": str(meta.get("hint") or ""),
                "status": status,
            }
        )

    primary = dict(policy.get("primary_cta_by_step") or {}).get(current) or {}
    if current == "materializar" and not eco_validated:
        primary = dict(policy.get("primary_cta_by_step") or {}).get("validar_economica") or primary

    capture_summary = format_honest_capture_summary(cap, economic_validated=eco_validated)

    return {
        "policy_version": policy_version(),
        "enabled": expediente_guided_enabled(),
        "current_step": current,
        "steps": steps_out,
        "primary_cta": primary,
        "capture_status": cap,
        "capture_summary": capture_summary,
        "panel_button_labels": labels,
        "generation_hints": hints,
        "overlay_kinds": policy.get("overlay_kinds") or {},
        "overlay_messages": ux.get("overlays") or {},
        "panel_hints": ux.get("panel_hints") or {},
        "flags": {
            "analysis_done": analysis_done,
            "capture_complete": bool(cap.get("capture_complete")),
            "economic_validated": eco_validated,
            "document_plan_ready": plan_ready,
        },
        "readiness": readiness if use_readiness else None,
    }


def mark_economic_validated_patch() -> Dict[str, Any]:
    """Parche de sesión al cerrar validación económica en chat."""
    from datetime import datetime, timezone

    return {
        "expediente_guided_v1": {
            "economic_validated_at": datetime.now(timezone.utc).isoformat(),
        }
    }
