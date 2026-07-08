"""
Política HRU de misión del expediente (prioridad cotizar / técnica / plan documental).

Fuente: ``app/contracts/expediente_mission_policy.json``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "expediente_mission_policy.json"


@lru_cache(maxsize=1)
def load_expediente_mission_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_expediente_mission_policy().get("policy_version") or "")


def _compiled_exclusion_patterns() -> List[Pattern[str]]:
    raw = (load_expediente_mission_policy().get("technical_slot_exclusions") or {}).get(
        "label_regex"
    ) or []
    out: List[Pattern[str]] = []
    for pat in raw:
        try:
            out.append(re.compile(str(pat)))
        except re.error:
            continue
    return out


def is_document_shell_technical_label(label: str) -> bool:
    """True si el requisito es el documento completo, no un dato capturable en chat."""
    text = str(label or "").strip()
    if not text:
        return True
    for pat in _compiled_exclusion_patterns():
        if pat.search(text):
            return True
    return False


def humanize_technical_slot_label(label: str, slot_kind: str = "") -> str:
    """Etiqueta legible para licitante (sin títulos de documento del compliance)."""
    human = load_expediente_mission_policy().get("technical_label_humanize") or {}
    kind = str(slot_kind or "").strip().lower()
    if kind and kind in human:
        return str(human[kind])
    raw = str(label or "").strip()
    if is_document_shell_technical_label(raw):
        if kind == "methodology" or "metodolog" in raw.lower():
            return str(human.get("methodology") or "metodología de ejecución")
        if kind == "workforce" or "personal" in raw.lower():
            return str(human.get("workforce") or "personal mínimo")
        return str(human.get("free_text_annex") or "detalle técnico")
    if len(raw) > 72:
        return raw[:69].rsplit(" ", 1)[0] + "…"
    return raw


def _session_name_lower(session_state: Dict[str, Any]) -> str:
    return str(session_state.get("name") or "").lower()


def session_has_strong_service_keyword(session_state: Dict[str, Any]) -> bool:
    """Señal fuerte (vigilancia, seguridad): cotización primero sin depender de flags de análisis."""
    cfg = load_expediente_mission_policy().get("economic_first") or {}
    name = _session_name_lower(session_state)
    for kw in cfg.get("strong_session_name_keywords") or []:
        if str(kw).lower() in name:
            return True
    return False


def session_has_work_context(session_state: Dict[str, Any]) -> bool:
    """True si la sesión ya tiene contexto de licitación (análisis, inventario, hooks)."""
    tasks = session_state.get("tasks_completed") or []
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_id = str(t.get("task") or "")
            if task_id.startswith("stage_completed:"):
                return True

    if isinstance(session_state.get("compliance_master_list"), dict):
        cml = session_state["compliance_master_list"]
        if any(isinstance(cml.get(k), list) and cml.get(k) for k in ("tecnico", "formatos", "economico", "administrativo")):
            return True

    if isinstance(session_state.get("document_inventory"), dict):
        items = session_state["document_inventory"].get("items")
        if isinstance(items, list) and items:
            return True

    for flag in (
        "technical_post_analysis_hook_pending",
        "economic_post_analysis_hook_pending",
        "capture_matrix_blocks",
        "session_line_items",
    ):
        if session_state.get(flag):
            return True

    return False


def session_analysis_complete(session_state: Dict[str, Any]) -> bool:
    """Compat: análisis explícito o cualquier contexto de trabajo post-intake."""
    tasks = session_state.get("tasks_completed") or []
    if isinstance(tasks, list):
        if any(
            str(t.get("task") or "").startswith("stage_completed:analysis")
            for t in tasks
            if isinstance(t, dict)
        ):
            return True
    return session_has_work_context(session_state)


def resolve_service_hint_from_session_name(session_state: Dict[str, Any]) -> Optional[str]:
    """Hint de cotización derivado del nombre de sesión (reglas en política, no convocante)."""
    cfg = load_expediente_mission_policy().get("economic_first") or {}
    name = _session_name_lower(session_state)
    for rule in cfg.get("service_hint_rules") or []:
        if not isinstance(rule, dict):
            continue
        hint = str(rule.get("hint") or "").strip()
        if not hint:
            continue
        for kw in rule.get("name_keywords") or []:
            if str(kw).lower() in name:
                return hint
    return None


def session_signals_service_pricing(session_state: Dict[str, Any]) -> bool:
    """True si el perfil sugiere cotización en chat (servicios, vigilancia, etc.)."""
    if session_has_strong_service_keyword(session_state):
        return True

    cfg = load_expediente_mission_policy().get("economic_first") or {}
    if cfg.get("require_work_context_for_weak_signals") and not session_has_work_context(session_state):
        return False

    triage = session_state.get("triage_context") if isinstance(session_state.get("triage_context"), dict) else {}
    cat = str(triage.get("tender_category") or "").upper()
    allowed_cats = {str(c).upper() for c in (cfg.get("tender_categories") or [])}
    if cat and cat in allowed_cats:
        return True

    name = _session_name_lower(session_state)
    for kw in cfg.get("session_name_keywords") or []:
        if str(kw).lower() in name:
            return True

    eco_cat = str(cfg.get("compliance_economic_category") or "economico")
    cml = session_state.get("compliance_master_list")
    if isinstance(cml, dict) and isinstance(cml.get(eco_cat), list) and cml.get(eco_cat):
        return True

    if session_state.get("session_line_items") or session_state.get("capture_matrix_blocks"):
        return True

    pending_eco = sum(
        1
        for q in (session_state.get("pending_questions") or [])
        if isinstance(q, dict)
        and str(q.get("type") or "")
        in ("economic_price", "economic_price_matrix", "economic_validation_blocking")
    )
    if pending_eco > 0:
        return True

    if session_state.get("economic_post_analysis_hook_pending"):
        return True

    return False


def use_baseline_when_only_shells() -> bool:
    raw = load_expediente_mission_policy().get("technical_slot_exclusions") or {}
    return bool(raw.get("use_baseline_when_only_excluded", True))
