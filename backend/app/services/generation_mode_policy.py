"""
Política HRU versionada para modos de generación desacoplados (F2).

Fuente canónica: ``app/contracts/generation_mode_policy.json``.
El flag ``DECOUPLED_GENERATION_ENABLED`` en settings solo habilita/deshabilita operación.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

from app.config.settings import settings
from app.contracts.generation_modes import GenerationMode

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "generation_mode_policy.json"
)

_ALL_JOB_IDS = (
    "datagap",
    "technical",
    "formats",
    "economic_writer",
    "packager",
    "delivery",
)


@lru_cache(maxsize=1)
def load_generation_mode_policy() -> Dict[str, Any]:
    """Carga la política versionada desde JSON."""
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_generation_mode_policy().get("policy_version") or "")


def decoupled_generation_enabled() -> bool:
    """True si el desacople F2 está habilitado por feature flag."""
    return bool(getattr(settings, "DECOUPLED_GENERATION_ENABLED", True))


def normalize_generation_mode(raw: Optional[str]) -> str:
    """
    Normaliza alias y valores externos al modo canónico.

    Si el desacople está deshabilitado, siempre retorna ``full`` (compatibilidad).
    """
    if not decoupled_generation_enabled():
        return GenerationMode.FULL.value

    policy = load_generation_mode_policy()
    aliases = policy.get("aliases") if isinstance(policy.get("aliases"), dict) else {}
    default_mode = str(policy.get("default_mode") or GenerationMode.FULL.value)

    token = str(raw or "").strip().lower()
    if not token:
        return default_mode
    if token in aliases:
        token = str(aliases[token]).strip().lower()
    if token in GenerationMode.values():
        return token
    return default_mode


def _mode_cfg(mode: str) -> Dict[str, Any]:
    modes = load_generation_mode_policy().get("modes")
    if not isinstance(modes, dict):
        return {}
    cfg = modes.get(mode)
    return cfg if isinstance(cfg, dict) else {}


def active_jobs_for_mode(mode: str) -> FrozenSet[str]:
    """Jobs que el modo ejecuta; el resto se marcan ``skipped``."""
    cfg = _mode_cfg(normalize_generation_mode(mode))
    active = cfg.get("jobs_active") or []
    return frozenset(str(j).strip() for j in active if str(j).strip())


def skipped_jobs_for_mode(mode: str) -> FrozenSet[str]:
    active = active_jobs_for_mode(mode)
    return frozenset(j for j in _ALL_JOB_IDS if j not in active)


def wipe_preserve_subdirs_for_mode(mode: str) -> List[str]:
    cfg = _mode_cfg(normalize_generation_mode(mode))
    raw = cfg.get("wipe_preserve_subdirs") or []
    return [str(s).strip() for s in raw if str(s).strip()]


def economic_snapshot_required_before(mode: str) -> FrozenSet[str]:
    cfg = _mode_cfg(normalize_generation_mode(mode))
    raw = cfg.get("economic_snapshot_required_before") or []
    return frozenset(str(j).strip() for j in raw if str(j).strip())


def resolve_generation_mode_from_input(
    input_data: Optional[Dict[str, Any]],
    session_state: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Cascada HRU: request explícito > company_data > generation_state previo > default.
    """
    data = input_data if isinstance(input_data, dict) else {}
    company = data.get("company_data") if isinstance(data.get("company_data"), dict) else {}

    for candidate in (
        data.get("generation_mode"),
        company.get("generation_mode"),
    ):
        if candidate:
            return normalize_generation_mode(str(candidate))

    session = session_state if isinstance(session_state, dict) else {}
    gen_state = session.get("generation_state")
    if isinstance(gen_state, dict) and gen_state.get("generation_mode"):
        return normalize_generation_mode(str(gen_state["generation_mode"]))

    return normalize_generation_mode(None)
