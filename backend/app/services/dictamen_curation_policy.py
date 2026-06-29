"""
Carga de política versionada para curación del Dictamen Forense (HRU).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "dictamen_curation_policy.json"
)


@lru_cache(maxsize=1)
def load_dictamen_curation_policy() -> Dict[str, Any]:
    """Carga dictamen_curation_policy.json (versionada, sin hardcode por sesión)."""
    raw = _POLICY_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("dictamen_curation_policy.json inválido")
    return data


def policy_version() -> str:
    return str(load_dictamen_curation_policy().get("policy_version") or "unknown")


def _compile_patterns(key: str) -> List[re.Pattern[str]]:
    pol = load_dictamen_curation_policy()
    out: List[re.Pattern[str]] = []
    for pat in pol.get(key) or []:
        if not pat:
            continue
        try:
            out.append(re.compile(str(pat)))
        except re.error:
            continue
    return out


def matches_any_pattern(blob: str, key: str) -> bool:
    text = str(blob or "")
    if not text.strip():
        return False
    for rx in _compile_patterns(key):
        if rx.search(text):
            return True
    return False


def actionable_tipo_accion_values() -> frozenset[str]:
    pol = load_dictamen_curation_policy()
    vals = pol.get("actionable_tipo_accion") or []
    return frozenset(str(v).strip().lower() for v in vals if v)


def actionable_non_compliance_categories() -> frozenset[str]:
    pol = load_dictamen_curation_policy()
    vals = pol.get("actionable_non_compliance_categories") or []
    return frozenset(str(v).strip().lower() for v in vals if v)
