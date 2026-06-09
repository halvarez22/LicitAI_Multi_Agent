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

_OBRA_PUBLICA_V1: Dict[str, Any] = {
    "min_months": None,
    "max_months": None,
    "iva_rate": 0.16,
    "indirectos_rate": 0.10,
    "utilidad_rate": 0.05,
    "desproporcion_threshold": 0.35,
    "ppe_formula": False,
    "formula_set": "obra_publica_v1",
    "fsr_required": False,
    "template_name": "obra_publica_economic",
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
    "perfil_obra_publica_v1": _OBRA_PUBLICA_V1,
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


def _reglas_from_session_state(session_state: Dict[str, Any]) -> Dict[str, str]:
    """Extrae reglas económicas del último ``analisis_bases`` persistido en sesión."""
    from app.services.analyst_output_normalize import normalize_reglas_economicas_dict

    for task in reversed(session_state.get("tasks_completed") or []):
        if task.get("task") == "analisis_bases":
            res = task.get("result")
            if isinstance(res, dict):
                raw = res.get("reglas_economicas")
                reglas = normalize_reglas_economicas_dict(raw)
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        text = str(value or "").strip()
                        if not text or text.lower() == "no especificado":
                            continue
                        reglas[f"raw_{key}"] = text
                return reglas
            break
    return {}


def session_requires_fsr_labor_profile(
    session_state: Dict[str, Any],
    session_id: str = "",
) -> bool:
    """
    True solo si la licitación activa perfil con FSR obligatorio (p. ej. salud/IMSS).

    Obras y licitaciones genéricas (catálogo de conceptos, PU) no deben pedir nómina FSR.
    """
    reglas = _reglas_from_session_state(session_state)
    profile_name = detect_profile(reglas, session_id)
    return bool(get_profile(profile_name).get("fsr_required"))
