"""
Contrato canónico economic_risk_evidence_v1 — procedencia HRU para riesgos económicos.

Sin hardcode por licitación; solo policy + índice + sesión.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SCHEMA_VERSION = "economic_risk_evidence_v1"

MATCH_ALTA = "alta"
MATCH_MEDIA = "media"
MATCH_BAJA = "baja"
MATCH_NONE = "none"

MODE_INDEX_VERIFIED = "index_verified"
MODE_INFERENCE_ONLY = "inference_only"
MODE_INDEX_ERROR = "index_error"


def build_evidence_v1(
    raw: Optional[Dict[str, Any]] = None,
    *,
    literal: str = "",
    error_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Normaliza bloque de evidencia forense v1."""
    raw = dict(raw or {})
    conf = str(raw.get("match_confidence") or MATCH_NONE).lower()
    page = raw.get("page")
    snippet = str(raw.get("snippet") or "").strip() or None
    source = raw.get("source")

    if error_type:
        mode = MODE_INDEX_ERROR
        conf = MATCH_NONE
    elif conf == MATCH_ALTA and page is not None and snippet:
        mode = MODE_INDEX_VERIFIED
    elif snippet or conf in (MATCH_ALTA, MATCH_MEDIA):
        mode = MODE_INFERENCE_ONLY if page is None else MODE_INDEX_VERIFIED
    else:
        mode = MODE_INFERENCE_ONLY
        conf = MATCH_NONE if not snippet else conf

    return {
        "schema_version": SCHEMA_VERSION,
        "literal": literal or raw.get("literal"),
        "page": page,
        "source": source if source not in (None, "dictamen", "dictamen_causales") else raw.get("document"),
        "snippet": snippet,
        "match_confidence": conf,
        "evidence_mode": mode,
        "provenance": raw.get("provenance") or raw.get("provenance_ui", {}).get("source"),
        "error_type": error_type,
        "provenance_ui": {
            "source": raw.get("provenance") or "evidence_v1",
            "page": page,
            "document": source,
            "match_confidence": conf,
            "evidence_mode": mode,
        },
    }


def merge_evidence_into_item(item: Dict[str, Any], evidence_v1: Dict[str, Any]) -> Dict[str, Any]:
    """Fusiona evidencia v1 en ítem de riesgo forense para panel/API."""
    ev = dict(evidence_v1 or {})
    out = {**item, "evidence_v1": ev}
    if ev.get("page") is not None:
        out["page"] = ev["page"]
    if ev.get("snippet"):
        out["snippet"] = ev["snippet"]
    if ev.get("source"):
        out["source"] = ev["source"]
    prov = dict(item.get("provenance_ui") or {})
    prov.update(ev.get("provenance_ui") or {})
    out["provenance_ui"] = prov
    return out
