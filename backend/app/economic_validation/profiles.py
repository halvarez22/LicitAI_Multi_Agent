from __future__ import annotations

from typing import Any, Dict


# Parámetros compartidos: anexos tipo sector salud / compras institucionales grandes (agnóstico del RFC del convocante).
_HEALTH_SECTOR_ANNEX_LIKE: Dict[str, Any] = {
    "min_months": 6,
    "max_months": 11,
    "iva_rate": 0.16,
    "desproporcion_threshold": 0.25,
    "ppe_formula": True,
    "template_name": "anexos_issste_8_9_9a_13",
}

PROFILES: Dict[str, Dict[str, Any]] = {
    "generic": {
        "min_months": None,
        "max_months": None,
        "iva_rate": 0.16,
        "desproporcion_threshold": 0.35,
        "ppe_formula": False,
        "template_name": "generic_economic",
    },
    "health_sector_annex_like": _HEALTH_SECTOR_ANNEX_LIKE,
    "issste_2024_like": _HEALTH_SECTOR_ANNEX_LIKE,
}

# Palabras clave en nombre de sesión o reglas (bases); ninguna fija un convocante concreto.
_HEALTH_SECTOR_SEED_MARKERS = (
    "issste",
    " imss",
    " imss ",
    "imss ",
    " isste",
    "isste",
    "sector salud",
    "servicios de salud",
    "instituto mexicano del seguro",
)


def detect_profile(reglas: Dict[str, str], session_name: str = "") -> str:
    blob = " ".join(str(v or "") for v in (reglas or {}).values()).lower()
    seed = f"{session_name} {blob}".lower()
    if any(m in seed for m in _HEALTH_SECTOR_SEED_MARKERS):
        return "health_sector_annex_like"
    return "generic"


def get_profile(profile_name: str) -> Dict[str, Any]:
    return PROFILES.get(profile_name, PROFILES["generic"])
