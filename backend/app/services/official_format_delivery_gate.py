"""
Gate de entrega: bloquea sobre si se esperaba machote oficial y no hay espejo verificable.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.config.settings import settings


def official_mirror_delivery_gate_enabled() -> bool:
    return bool(getattr(settings, "OFFICIAL_MIRROR_DELIVERY_GATE_ENABLED", True))


def validate_official_mirror_delivery(
    *,
    stage: str = "economic",
    generated_documents: Optional[Sequence[Dict[str, Any]]] = None,
    doc_metadata_list: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Evalúa documentos con ``official_template_expected`` sin ``official_bases_mirror``.

    Returns:
        Dict con validation_passed, issues y conteos.
    """
    if not official_mirror_delivery_gate_enabled():
        return {
            "validation_passed": True,
            "issues": [],
            "stage": stage,
            "gate": "official_mirror",
            "skipped": True,
        }

    issues: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    for doc in generated_documents or []:
        if isinstance(doc, dict):
            sources.append(doc)
    for meta in doc_metadata_list or []:
        if isinstance(meta, dict):
            sources.append(meta)

    seen: set[str] = set()
    for item in sources:
        path = str(item.get("ruta") or item.get("path") or item.get("filename") or "")
        dedupe = str(item.get("dedupe_key") or "")
        key = dedupe or path
        if key in seen:
            continue
        seen.add(key)

        expected = bool(
            item.get("official_template_expected")
            or (item.get("provenance_ui") or {}).get("official_template_expected")
        )
        mirror = bool(
            item.get("official_bases_mirror")
            or (item.get("provenance_ui") or {}).get("official_bases_mirror")
        )
        if not expected:
            continue
        if mirror:
            continue
        label = str(
            item.get("document_title")
            or item.get("nombre")
            or dedupe
            or path
        )
        issues.append(
            {
                "severity": "blocking",
                "error_type": "official_template_not_mirrored",
                "dedupe_key": dedupe,
                "path": path,
                "label": label,
                "stage": stage,
                "user_message": (
                    f"El anexo **{label}** exige el formato publicado en bases, "
                    "pero el documento generado no es un espejo verificable. "
                    "Revise la indexación de bases o complete el formato antes de cerrar el sobre."
                ),
            }
        )

    return {
        "validation_passed": len(issues) == 0,
        "issues": issues,
        "blocking_count": len(issues),
        "stage": stage,
        "gate": "official_mirror",
    }
