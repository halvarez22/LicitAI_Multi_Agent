"""
UX HRU para bloqueos y captura FSR en copiloto económico.

Fuente canónica: ``app/contracts/economic_fsr_ux_messages.json``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.economic_fsr_policy import fsr_param_labels_human

_UX_PATH = Path(__file__).resolve().parents[1] / "contracts" / "economic_fsr_ux_messages.json"


@lru_cache(maxsize=1)
def load_economic_fsr_ux_messages() -> Dict[str, Any]:
    with _UX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def messages_version() -> str:
    return str(load_economic_fsr_ux_messages().get("messages_version") or "")


def _session_name(session_state: Optional[Dict[str, Any]]) -> str:
    state = session_state or {}
    name = str(state.get("name") or "").strip()
    return name or "esta licitación"


def parse_missing_fsr_keys(blocking_issues: List[str]) -> List[str]:
    """Extrae claves faltantes del mensaje determinista del motor."""
    keys: List[str] = []
    for issue in blocking_issues or []:
        text = str(issue or "")
        m = re.search(r"\(([^)]+)\)", text)
        if not m:
            continue
        for part in m.group(1).split(","):
            token = part.strip()
            if token and token not in keys:
                keys.append(token)
    return keys


def build_fsr_blocking_chat_message(
    *,
    blocking_issues: List[str],
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """Mensaje Gate 5 / chat cuando faltan parámetros FSR."""
    tpl = (
        (load_economic_fsr_ux_messages().get("error_types") or {})
        .get("fsr_required_params_missing")
        or {}
    )
    missing_keys = parse_missing_fsr_keys(blocking_issues)
    ctx = {
        "session_name": _session_name(session_state),
        "missing_labels": fsr_param_labels_human(missing_keys),
    }
    parts = [
        str(tpl.get("lead") or "").format(**ctx),
        str(tpl.get("detail") or "").format(**ctx),
        str(tpl.get("cta") or "").format(**ctx),
    ]
    return "\n\n".join(p for p in parts if p.strip())


def build_fsr_pending_question(
    *,
    blocking_issues: List[str],
    session_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pregunta pendiente ``economic_validation_blocking`` para cola HITL."""
    tpl = load_economic_fsr_ux_messages().get("pending_question") or {}
    err_tpl = (
        (load_economic_fsr_ux_messages().get("error_types") or {})
        .get("fsr_required_params_missing")
        or {}
    )
    missing_keys = parse_missing_fsr_keys(blocking_issues)
    ctx = {
        "session_name": _session_name(session_state),
        "missing_labels": fsr_param_labels_human(missing_keys),
    }
    return {
        "field": str(tpl.get("field") or "validation_rule_fsr_required"),
        "label": str(tpl.get("label") or "Completar parámetros FSR"),
        "question": str(blocking_issues[0] if blocking_issues else err_tpl.get("detail") or "").format(**ctx),
        "document_hint": str(err_tpl.get("document_hint") or "").format(**ctx),
        "type": str(tpl.get("type") or "economic_validation_blocking"),
        "error_type": "fsr_required_params_missing",
        "blocking_items": missing_keys,
    }
