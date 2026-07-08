"""
Política HRU versionada: defer de hallazgos económicos en etapa administrativa.

Fuente canónica: ``app/contracts/document_fill_deferral_policy.json``.
El flag ``ADMIN_ECONOMIC_DEFERRAL`` en settings solo habilita/deshabilita operación.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, Sequence, Tuple

from app.config.settings import settings

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "document_fill_deferral_policy.json"
)


@lru_cache(maxsize=1)
def load_document_fill_deferral_policy() -> Dict[str, Any]:
    """Carga la política versionada desde JSON."""
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_document_fill_deferral_policy().get("policy_version") or "")


@lru_cache(maxsize=1)
def _admin_cfg() -> Dict[str, Any]:
    raw = load_document_fill_deferral_policy().get("admin_economic_deferral")
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=1)
def _compiled_placeholder_patterns() -> Tuple[re.Pattern[str], ...]:
    patterns = _admin_cfg().get("placeholder_text_patterns") or []
    return tuple(re.compile(str(p)) for p in patterns if str(p).strip())


@lru_cache(maxsize=1)
def _compiled_filename_patterns() -> Tuple[re.Pattern[str], ...]:
    patterns = _admin_cfg().get("filename_patterns") or []
    return tuple(re.compile(str(p)) for p in patterns if str(p).strip())


@lru_cache(maxsize=1)
def deferred_field_keys() -> FrozenSet[str]:
    keys = _admin_cfg().get("field_keys") or []
    return frozenset(str(k).lower() for k in keys if str(k).strip())


def admin_economic_deferral_active(stage: str) -> bool:
    """True si la política difiere hallazgos económicos en la etapa indicada."""
    if not bool(getattr(settings, "ADMIN_ECONOMIC_DEFERRAL", True)):
        return False
    cfg = _admin_cfg()
    if not bool(cfg.get("enabled", True)):
        return False
    stages = {str(s).strip().lower() for s in (cfg.get("stages") or ["formats"])}
    return str(stage or "").strip().lower() in stages


def deferred_expected_rule() -> str:
    return str(_admin_cfg().get("expected_rule") or "deferred_to_economic_stage")


def matches_deferred_economic_placeholder(text: str, *, basename: str = "") -> bool:
    blob = f"{basename} {text or ''}"
    return any(pattern.search(blob) for pattern in _compiled_placeholder_patterns())


def matches_deferred_economic_filename(basename: str) -> bool:
    name = str(basename or "")
    if not name:
        return False
    return any(pattern.search(name) for pattern in _compiled_filename_patterns())


def should_defer_standalone_ellipsis() -> bool:
    return bool(_admin_cfg().get("defer_standalone_ellipsis", True))


def should_defer_formats_economic_issue(
    *,
    stage: str,
    field_key: str = "",
    basename: str = "",
    error_type: str = "",
    expected_rule: str = "",
) -> bool:
    """Indica si un hallazgo económico debe bajar a warning en etapa administrativa."""
    if not admin_economic_deferral_active(stage):
        return False
    rule = str(expected_rule or "")
    if rule in {deferred_expected_rule(), "deferred_to_economic_stage"}:
        return True
    fk = str(field_key or "").lower()
    if fk in deferred_field_keys():
        return True
    if str(error_type or "") == "placeholder_detected" and matches_deferred_economic_filename(
        basename
    ):
        return True
    return False
