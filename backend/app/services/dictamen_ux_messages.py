"""
Mensajes UX centralizados para Dictamen Forense (salud dual extracción vs auditoría).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _status_label(status: str) -> str:
    st = str(status or "").lower()
    if st == "ok":
        return "correcta"
    if st == "degraded":
        return "parcial"
    if st in ("failed", "fail", "error"):
        return "con problemas"
    if st == "partial":
        return "con incidencias"
    return st or "desconocida"


def build_dictamen_ux_guia(
    extraction_health: Optional[Dict[str, Any]],
    forensic_audit_health: Optional[Dict[str, Any]],
) -> str:
    """Guía no técnica cuando extracción y auditoría divergen."""
    ext_st = str((extraction_health or {}).get("status") or "").lower()
    fore_st = str((forensic_audit_health or {}).get("status") or "").lower()

    if ext_st == "failed":
        return (
            "No se pudo leer o indexar correctamente el PDF de bases. "
            "Sube de nuevo el archivo o reprocesa el documento antes de confiar en el dictamen."
        )

    if ext_st in ("ok", "degraded") and fore_st in ("partial", "failed", "fail"):
        zones_p: List[str] = []
        zones_f: List[str] = []
        if isinstance(forensic_audit_health, dict):
            zones_p = list(forensic_audit_health.get("zones_partial") or [])
            zones_f = list(forensic_audit_health.get("zones_failed") or [])
        parts: List[str] = []
        if zones_f:
            parts.append(f"fallos en: {', '.join(zones_f)}")
        if zones_p:
            parts.append(f"parciales en: {', '.join(zones_p)}")
        detail = f" ({'; '.join(parts)})" if parts else ""
        return (
            "Las bases se leyeron e indexaron correctamente (materia prima lista). "
            f"La auditoría automática de requisitos terminó con incidencias{detail}. "
            "Usa la lista de obligaciones como checklist principal; revisa manualmente las zonas marcadas "
            "o vuelve a analizar si hubo bloques vacíos del motor de IA."
        )

    if ext_st == "ok" and fore_st in ("ok", "success", ""):
        return (
            "Las bases se leyeron correctamente y la auditoría forense no reportó incidencias relevantes. "
            "Revisa igualmente las obligaciones antes de generar la propuesta."
        )

    return (
        f"Lectura de bases: {_status_label(ext_st)}. "
        f"Auditoría forense: {_status_label(fore_st)}."
    )


def build_extraction_badge(extraction_health: Optional[Dict[str, Any]]) -> Dict[str, str]:
    st = str((extraction_health or {}).get("status") or "unknown").lower()
    if st == "ok":
        return {"label": "Lectura de bases", "status": "ok", "color": "#2ecc71"}
    if st == "degraded":
        return {"label": "Lectura de bases", "status": "degraded", "color": "#f39c12"}
    return {"label": "Lectura de bases", "status": "failed", "color": "#e74c3c"}


def build_forensic_badge(forensic_audit_health: Optional[Dict[str, Any]]) -> Dict[str, str]:
    st = str((forensic_audit_health or {}).get("status") or "unknown").lower()
    if st in ("ok", "success"):
        return {"label": "Auditoría forense", "status": "ok", "color": "#2ecc71"}
    if st == "partial":
        return {"label": "Auditoría forense", "status": "partial", "color": "#f39c12"}
    return {"label": "Auditoría forense", "status": "failed", "color": "#e74c3c"}
