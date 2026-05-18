"""
Resolución de política dinámica de validaciones por sesión/convocatoria.

Prioridad de decisión:
1) Reglas críticas por error_type (nunca skip)
2) Override por error_type en session_state.validation_policy.error_type_overrides
3) Override global en session_state.validation_policy.allow_skip_with_justification
4) Heurística por entidad estricta (ISSSTE/CFE/PEMEX/IMSS, configurable por env)
5) Default permissivo para advertencias
"""

from __future__ import annotations

import os
from typing import Any, Dict

_CRITICAL_NEVER_SKIP = {
    "precios_positivos",
    "total_base_cotizable",
    "missing_mandatory_field",
    "signature_pending",
    "consistencia_subtotales",
}


def _strict_entities() -> list[str]:
    raw = os.getenv("VALIDATION_STRICT_ENTITIES", "issste,cfe,pemex,imss")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def resolve_validation_policy(
    session_state: Dict[str, Any] | None,
    *,
    error_type: str,
) -> Dict[str, Any]:
    """Calcula política efectiva para una validación dada."""
    session_state = session_state or {}
    et = str(error_type or "").strip().lower()

    if et in _CRITICAL_NEVER_SKIP:
        return {"allow_skip_with_justification": False, "policy_source": "critical_never_skip"}

    vp = session_state.get("validation_policy") if isinstance(session_state, dict) else None
    if isinstance(vp, dict):
        per_error = vp.get("error_type_overrides")
        if isinstance(per_error, dict):
            pe = per_error.get(et)
            if isinstance(pe, dict) and "allow_skip_with_justification" in pe:
                return {
                    "allow_skip_with_justification": bool(pe.get("allow_skip_with_justification")),
                    "policy_source": "session_error_type_override",
                }
        if "allow_skip_with_justification" in vp:
            return {
                "allow_skip_with_justification": bool(vp.get("allow_skip_with_justification")),
                "policy_source": "session_global_override",
            }

    session_name = str(session_state.get("name") or session_state.get("session_id") or "").lower()
    licitacion_id = str(session_state.get("licitacion_id") or "").lower()
    corpus = f"{session_name} {licitacion_id}".strip()
    if corpus and any(ent in corpus for ent in _strict_entities()):
        return {"allow_skip_with_justification": False, "policy_source": "strict_entity_match"}

    return {"allow_skip_with_justification": True, "policy_source": "default_permissive"}

