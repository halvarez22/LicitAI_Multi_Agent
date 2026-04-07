from __future__ import annotations

from typing import Any, Dict


PROFILES: Dict[str, Dict[str, Any]] = {
    "generic": {
        "min_months": None,
        "max_months": None,
        "iva_rate": 0.16,
        "desproporcion_threshold": 0.35,
        "ppe_formula": False,
        "template_name": "generic_economic",
    },
    "issste_2024_like": {
        "min_months": 6,
        "max_months": 11,
        "iva_rate": 0.16,
        "desproporcion_threshold": 0.25,
        "ppe_formula": True,
        "template_name": "anexos_issste_8_9_9a_13",
    },
}


def detect_profile(reglas: Dict[str, str], session_name: str = "") -> str:
    blob = " ".join(str(v or "") for v in (reglas or {}).values()).lower()
    seed = f"{session_name} {blob}".lower()
    if "issste" in seed:
        return "issste_2024_like"
    return "generic"


def get_profile(profile_name: str) -> Dict[str, Any]:
    return PROFILES.get(profile_name, PROFILES["generic"])
