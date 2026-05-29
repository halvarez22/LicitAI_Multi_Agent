"""
Gate universal antes de FINAL_OK: anexos económicos esperados vs materializados.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.delivery_coverage_report import build_delivery_coverage_report
from app.services.structured_economic_price_mapper import build_structured_price_slots


def _economic_catalog_rows(coverage: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = coverage.get("rows") or []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        doc_class = str(row.get("document_class") or "").lower()
        accion = str(row.get("accion_recomendada") or "").lower()
        if "economic" in doc_class or accion in ("generar", "requiere_datos_licitante"):
            ext = str(row.get("source_filename") or "").lower()
            if ext.endswith((".xlsx", ".xls")) or "propuesta econom" in ext or "anexo iii" in ext:
                out.append(row)
    return out


def evaluate_economic_coverage_before_final_ok(
    session_state: Dict[str, Any],
    session_id: str,
    *,
    documents: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retorna dict bloqueante si faltan precios estructurados o plantillas económicas en entrega.
    """
    line_items = list(session_state.get("session_line_items") or [])
    inputs = session_state.get("economic_user_inputs") or {}
    slots = build_structured_price_slots(line_items, inputs)
    missing_prices = [s for s in slots if s.get("captured_price") is None]
    if missing_prices:
        return {
            "code": "STRUCTURED_PRICES_PENDING",
            "message": (
                f"Faltan **{len(missing_prices)}** precio(s) en anexos económicos estructurados "
                "antes de cerrar el expediente."
            ),
            "missing_price_count": len(missing_prices),
            "missing_slots": [
                {
                    "field": s.get("field"),
                    "label": s.get("label"),
                    "source_name": s.get("source_name"),
                }
                for s in missing_prices[:20]
            ],
        }

    docs = documents if documents is not None else list(session_state.get("documents") or [])
    try:
        coverage = build_delivery_coverage_report(session_id, session_state, docs)
    except Exception:
        return None

    pending_templates: List[str] = []
    for row in _economic_catalog_rows(coverage):
        estado = str(row.get("estado_cobertura") or "")
        if estado == "pendiente_generar":
            pending_templates.append(str(row.get("source_filename") or "plantilla"))

    if pending_templates:
        return {
            "code": "ECONOMIC_TEMPLATE_NOT_GENERATED",
            "message": (
                f"Faltan **{len(pending_templates)}** plantilla(s) económica(s) en el paquete validado."
            ),
            "pending_templates": pending_templates[:15],
        }
    return None
