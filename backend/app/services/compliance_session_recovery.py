"""
Recuperación de ``compliance_master_list`` cuando la sesión quedó incompleta
(p. ej. guardado parcial tras importar Excel en chat).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_CATEGORY_TO_BUCKET = {
    "administrativo": "administrativo",
    "legal_administrative": "administrativo",
    "legal": "administrativo",
    "formatos": "formatos",
    "tecnico": "tecnico",
    "technical": "tecnico",
    "economico": "formatos",
    "economic": "formatos",
}


def _has_compliance_buckets(data: Dict[str, Any]) -> bool:
    return any(
        isinstance(data.get(k), list) and data.get(k)
        for k in ("administrativo", "tecnico", "formatos")
    )


def _from_tasks(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for task in reversed(session_state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        tname = str(task.get("task") or "")
        if tname not in ("stage_completed:compliance", "master_compliance_list"):
            continue
        res = task.get("result") or {}
        data = res.get("data") if isinstance(res.get("data"), dict) else res
        if isinstance(data, dict) and _has_compliance_buckets(data):
            return data
    return None


def _from_mini_dictamen(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = session_state.get("mini_dictamen_anexos")
    if not isinstance(raw, dict):
        return None
    items = [it for it in (raw.get("items") or []) if isinstance(it, dict)]
    if not items:
        return None

    out: Dict[str, List[Dict[str, Any]]] = {
        "administrativo": [],
        "tecnico": [],
        "formatos": [],
    }
    for idx, it in enumerate(items):
        cat = str(it.get("category") or "administrativo").lower()
        bucket = _CATEGORY_TO_BUCKET.get(cat, "administrativo")
        nombre = str(it.get("display_name") or it.get("canonical_id") or f"anexo_{idx}").strip()
        if not nombre:
            continue
        notes = it.get("notes") or []
        desc = " ".join(str(n) for n in notes if n) if notes else nombre
        out[bucket].append(
            {
                "id": str(it.get("canonical_id") or f"recovered_mini_{idx}"),
                "nombre": nombre,
                "descripcion": desc[:500],
                "snippet": desc[:240] or nombre,
                "archivo_fuente": it.get("source_filename"),
                "tipo_accion": it.get("delivery_action") or "generar",
                "match_tier": "recovered",
                "_recovered_from": "mini_dictamen_anexos",
            }
        )
    return out if _has_compliance_buckets(out) else None


def _from_template_catalog(session_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = session_state.get("session_template_catalog")
    if not isinstance(raw, dict):
        return None
    items = [it for it in (raw.get("items") or []) if isinstance(it, dict)]
    if not items:
        return None

    out: Dict[str, List[Dict[str, Any]]] = {
        "administrativo": [],
        "tecnico": [],
        "formatos": [],
    }
    for idx, it in enumerate(items):
        doc_class = str(it.get("document_class") or "").lower()
        if doc_class == "plantilla_oferta":
            bucket = "formatos"
        elif "tecn" in doc_class:
            bucket = "tecnico"
        else:
            bucket = "administrativo"
        nombre = str(it.get("source_filename") or it.get("display_name") or f"plantilla_{idx}")
        out[bucket].append(
            {
                "id": f"recovered_cat_{idx}",
                "nombre": nombre,
                "descripcion": nombre,
                "snippet": nombre,
                "archivo_fuente": it.get("source_filename"),
                "match_tier": "recovered",
                "_recovered_from": "session_template_catalog",
            }
        )
    return out if _has_compliance_buckets(out) else None


def try_recover_compliance_master_list(
    session_state: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Intenta reconstruir la lista maestra desde artefactos que sobrevivieron al wipe.

    Returns:
        (lista, fuente) o (None, motivo)
    """
    existing = session_state.get("compliance_master_list")
    if isinstance(existing, dict) and _has_compliance_buckets(existing):
        return existing, "compliance_master_list"

    for fn, label in (
        (_from_tasks, "tasks_completed"),
        (_from_mini_dictamen, "mini_dictamen_anexos"),
        (_from_template_catalog, "session_template_catalog"),
    ):
        data = fn(session_state)
        if data:
            return data, label
    return None, "sin_fuente_recuperable"
