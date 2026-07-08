"""
Política HRU de piloto on-premise (F10).

Fuente canónica: ``app/contracts/pilot_onprem_policy.json``.
Valida flags runtime vs perfil piloto recomendado (sin hardcode por cliente).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.config.settings import settings

_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "pilot_onprem_policy.json"
)


@lru_cache(maxsize=1)
def load_pilot_onprem_policy() -> Dict[str, Any]:
    with _POLICY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def policy_version() -> str:
    return str(load_pilot_onprem_policy().get("policy_version") or "")


def pilot_profile_flags() -> Dict[str, bool]:
    raw = load_pilot_onprem_policy().get("pilot_profile")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, bool] = {}
    for key, val in raw.items():
        if isinstance(val, bool):
            out[str(key)] = val
    return out


def signoff_criteria() -> List[Dict[str, str]]:
    raw = load_pilot_onprem_policy().get("signoff_criteria")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def contract_dependencies() -> List[str]:
    raw = load_pilot_onprem_policy().get("contract_dependencies")
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if str(x).strip()]


def evaluate_pilot_runtime() -> Dict[str, Any]:
    """
    Compara settings actuales con el perfil piloto recomendado.

    Returns:
        dict con ``ok``, ``warnings``, ``errors``, ``profile_matches``.
    """
    expected = pilot_profile_flags()
    warnings: List[str] = []
    errors: List[str] = []
    matches: Dict[str, Dict[str, Any]] = {}

    for key, want in expected.items():
        have = bool(getattr(settings, key, want))
        matches[key] = {"expected": want, "actual": have, "match": have == want}
        if have != want:
            msg = f"Flag {key}: esperado {want} (piloto HRU), actual {have}"
            if key == "PACKAGING_REQUIRE_ALL_SOBRES" and have:
                warnings.append(msg + " — modo estricto; OK post sign-off")
            else:
                warnings.append(msg)

    contracts_root = _POLICY_PATH.parent
    for rel in contract_dependencies():
        path = contracts_root / rel
        if not path.is_file():
            errors.append(f"Contrato faltante: {rel}")

    ok = not errors
    return {
        "ok": ok,
        "policy_version": policy_version(),
        "warnings": warnings,
        "errors": errors,
        "profile_matches": matches,
    }
