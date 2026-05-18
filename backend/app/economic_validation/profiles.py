import json
import os
from typing import Any, Dict


# Carga de marcadores desde configuración externa para desacoplar el motor de casos específicos
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "profiles_config.json")
try:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _MARKERS_CONFIG = json.load(f)
except Exception:
    _MARKERS_CONFIG = {}

# Perfil para licitaciones con cálculo de Factor de Salario Real (FSR) y anexos complejos
_SALARIO_REAL_V1: Dict[str, Any] = {
    "min_months": 6,
    "max_months": 11,
    "iva_rate": 0.16,
    "desproporcion_threshold": 0.25,
    "ppe_formula": True,
    "formula_set": "salario_real_v1",
    "fsr_required": True,
    "template_name": "anexos_salario_real_fsr_v1",
}

PROFILES: Dict[str, Dict[str, Any]] = {
    "generic": {
        "min_months": None,
        "max_months": None,
        "iva_rate": 0.16,
        "desproporcion_threshold": 0.35,
        "ppe_formula": False,
        "formula_set": "generic_v1",
        "fsr_required": False,
        "template_name": "generic_economic",
    },
    "perfil_con_salario_real_v1": _SALARIO_REAL_V1,
}


def detect_profile(reglas: Dict[str, str], session_name: str = "") -> str:
    """Detecta el perfil de cálculo basado en palabras clave cargadas de la configuración externa."""
    blob = " ".join(str(v or "") for v in (reglas or {}).values()).lower()
    seed = f"{session_name} {blob}".lower()

    for profile_id, markers in _MARKERS_CONFIG.items():
        if any(m in seed for m in markers):
            return profile_id

    return "generic"


def get_profile(profile_name: str) -> Dict[str, Any]:
    """Recupera la configuración completa de un perfil o el genérico por defecto."""
    return PROFILES.get(profile_name, PROFILES["generic"])
