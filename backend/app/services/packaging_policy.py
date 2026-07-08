"""
Política HRU versionada para empaquetado parcial (F3.3).

Fuente canónica: ``app/contracts/packaging_policy.json``.
``PACKAGING_REQUIRE_ALL_SOBRES`` en settings habilita modo estricto producción.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List

from app.config.settings import settings

_POLICY_PATH = Path(__file__).resolve().parents[1] / "contracts" / "packaging_policy.json"


@lru_cache(maxsize=1)
def load_packaging_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_packaging_policy().get("policy_version") or "")


def require_all_sobres() -> bool:
    """True = falla empaquetado si falta algún sobre esperado (producción estricta)."""
    return bool(getattr(settings, "PACKAGING_REQUIRE_ALL_SOBRES", False))


@lru_cache(maxsize=1)
def expected_sobres() -> FrozenSet[str]:
    raw = load_packaging_policy().get("expected_sobres") or []
    return frozenset(str(s).strip() for s in raw if str(s).strip())


def partial_manifest_label() -> str:
    return str(
        load_packaging_policy().get("partial_manifest_label")
        or "Expediente parcial"
    )


def coverage_status_labels() -> Dict[str, str]:
    raw = load_packaging_policy().get("coverage_status_values")
    return raw if isinstance(raw, dict) else {}
