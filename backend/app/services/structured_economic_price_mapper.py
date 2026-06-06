"""
Helpers universales para anexos económicos estructurados con cantidades fijas
y columnas de precio vacías provistas por la convocante.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


def _norm_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _slug(value: Any, *, limit: int = 80) -> str:
    text = _norm_text(value)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:limit] if limit > 0 else text


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
        return out
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    num = _safe_float(value)
    if num is None:
        return None
    try:
        return int(num)
    except (TypeError, ValueError):
        return None


def _row_extra(row: Dict[str, Any]) -> Dict[str, Any]:
    extra = row.get("extra")
    return extra if isinstance(extra, dict) else {}


def _concept_text(row: Dict[str, Any]) -> str:
    return str(row.get("concepto_raw") or row.get("concepto_norm") or "").strip()


def _is_structured_template_row(row: Dict[str, Any]) -> bool:
    extra = _row_extra(row)
    return _norm_text(extra.get("layout")) == "structured_template"


def _service_slot_identity(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    extra = _row_extra(row)
    if _norm_text(extra.get("template_kind")) != "service_zone_elements":
        return None
    zone = str(extra.get("zone") or "").strip().upper()
    schedule = str(extra.get("schedule") or "").strip()
    if not zone or not schedule:
        return None
    return zone, schedule


def _location_slot_identity(row: Dict[str, Any]) -> Optional[str]:
    extra = _row_extra(row)
    if _norm_text(extra.get("template_kind")) != "location_price_grid":
        return None
    loc = str(extra.get("location_label") or row.get("concepto_raw") or "").strip()
    return loc if loc else None


def _material_slot_identity(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    extra = _row_extra(row)
    if _norm_text(extra.get("template_kind")) != "monthly_material_requirement":
        return None
    concept = str(row.get("concepto_raw") or row.get("concepto_norm") or "").strip()
    unit = str(row.get("unidad") or "").strip()
    if not concept:
        return None
    return concept, unit


def _slot_field_and_label(row: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    service_identity = _service_slot_identity(row)
    if service_identity:
        zone, schedule = service_identity
        field = f"price_struct_service_{_slug(zone, limit=8)}_{_slug(schedule, limit=48)}"
        concept_label = f"Zona {zone} | {schedule} | costo por elemento"
        return field, f"Precio (sin IVA): {concept_label}", concept_label

    location = _location_slot_identity(row)
    if location:
        field = f"price_struct_location_{_slug(location, limit=64)}"
        concept_label = location
        return field, f"Precio: {concept_label}", concept_label

    material_identity = _material_slot_identity(row)
    if material_identity:
        concept, unit = material_identity
        field = f"price_struct_material_{_slug(concept, limit=64)}"
        concept_label = concept if not unit else f"{concept} ({unit})"
        return field, f"Precio (sin IVA): {concept_label}", concept_label
    return None


def _slot_signature(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    meta = _slot_field_and_label(row)
    if not meta:
        return None
    field, _, concept_label = meta
    return field, concept_label


def _build_material_quantity_support_map(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Localiza anexos/formatos soporte de cantidades de materiales sin depender del filename.

    La detección es semántica-estructural: busca documentos distintos al grid de captura
    que contengan un solapamiento alto de conceptos de material contra los slots
    estructurados por cotizar. No altera el cálculo; solo agrega procedencia legible.
    """
    target_concepts = {
        _norm_text(_concept_text(row))
        for row in (rows or [])
        if isinstance(row, dict) and _material_slot_identity(row)
    }
    if not target_concepts:
        return {}

    doc_stats: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if _material_slot_identity(row):
            continue
        extra = _row_extra(row)
        source_name = str(extra.get("source_filename") or "").strip()
        if not source_name:
            continue
        doc_key = str(row.get("document_id") or source_name)
        stats = doc_stats.setdefault(
            doc_key,
            {
                "source_name": source_name,
                "total_rows": 0,
                "sheet_names": set(),
                "rows_with_anchor": 0,
                "document_roles": set(),
            },
        )
        stats["total_rows"] += 1
        sheet_name = str(row.get("sheet_name") or "").strip()
        if sheet_name:
            stats["sheet_names"].add(sheet_name)
        if _safe_int(row.get("row_index")) is not None:
            stats["rows_with_anchor"] += 1
        role = str(extra.get("document_role") or "").strip()
        if role:
            stats["document_roles"].add(role)

    docs: Dict[str, Dict[str, Any]] = {}
    support: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if _material_slot_identity(row):
            continue
        extra = _row_extra(row)
        source_name = str(extra.get("source_filename") or "").strip()
        if not source_name:
            continue
        concept = _concept_text(row)
        if not concept:
            continue
        key = _norm_text(concept)
        if key not in target_concepts:
            continue
        doc_key = str(row.get("document_id") or source_name)
        stats = doc_stats.get(doc_key) or {}
        bucket = docs.setdefault(
            doc_key,
            {
                "source_name": source_name,
                "matches": {},
                "concepts": set(),
                "matched_sheet_names": set(),
                "matched_rows_with_anchor": 0,
                "total_rows": int(stats.get("total_rows") or 0),
                "total_sheet_count": len(stats.get("sheet_names") or set()),
                "total_rows_with_anchor": int(stats.get("rows_with_anchor") or 0),
                "has_canonical_material_support_role": any(
                    str(role).startswith("material_support_")
                    for role in (stats.get("document_roles") or set())
                ),
            },
        )
        bucket["concepts"].add(key)
        sheet_name = str(row.get("sheet_name") or "").strip()
        if sheet_name:
            bucket["matched_sheet_names"].add(sheet_name)
        if _safe_int(row.get("row_index")) is not None:
            bucket["matched_rows_with_anchor"] += 1
        bucket["matches"].setdefault(
            key,
            {
                "source_name": source_name,
                "sheet_name": sheet_name or None,
                "row_index": _safe_int(row.get("row_index")),
            },
        )

    if not docs:
        return {}

    ranked_docs = sorted(
        docs.values(),
        key=lambda doc: (
            len(doc.get("matches") or {}),
            1 if doc.get("has_canonical_material_support_role") else 0,
            int(doc.get("total_rows") or 0),
            int(doc.get("total_sheet_count") or 0),
            int(doc.get("total_rows_with_anchor") or 0),
            len(doc.get("matched_sheet_names") or set()),
            int(doc.get("matched_rows_with_anchor") or 0),
        ),
        reverse=True,
    )
    min_overlap = 1 if len(target_concepts) <= 2 else (2 if len(target_concepts) <= 6 else 3)
    best_doc = ranked_docs[0]
    if len(best_doc.get("matches") or {}) < min_overlap:
        return {}

    for key, match in (best_doc.get("matches") or {}).items():
        support[key] = {
            "source_name": match.get("source_name") or best_doc.get("source_name"),
            "sheet_name": match.get("sheet_name"),
            "row_index": match.get("row_index"),
        }
    return support


def _resolve_slot_price(slot: Dict[str, Any], concept_prices: Dict[str, Any]) -> Optional[float]:
    if not isinstance(concept_prices, dict) or not concept_prices:
        return None

    candidates: List[str] = []
    field = str(slot.get("field") or "").strip()
    label = str(slot.get("label") or "").strip()
    concept_label = str(slot.get("concept_label") or "").strip()
    if field:
        candidates.append(field)
    if label:
        candidates.append(label)
    if concept_label:
        candidates.append(concept_label)

    norm_prices: Dict[str, float] = {}
    for key, value in concept_prices.items():
        num = _safe_float(value)
        if num is None:
            continue
        norm_prices[str(key)] = num
        norm_prices[_norm_text(key)] = num

    for key in candidates:
        if key in norm_prices:
            return norm_prices[key]
        nkey = _norm_text(key)
        if nkey in norm_prices:
            return norm_prices[nkey]
    return None


def build_structured_price_slots(
    rows: List[Dict[str, Any]],
    concept_prices: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Agrupa renglones estructurados en slots de captura de precio reutilizables."""
    grouped: Dict[str, Dict[str, Any]] = {}
    material_support_map = _build_material_quantity_support_map(rows)

    for row in rows or []:
        if not isinstance(row, dict) or not _is_structured_template_row(row):
            continue
        meta = _slot_field_and_label(row)
        if not meta:
            continue
        field, label, concept_label = meta
        extra = _row_extra(row)
        qty = _safe_float(row.get("cantidad")) or 0.0
        row_ref = {
            "document_id": row.get("document_id"),
            "sheet_name": row.get("sheet_name"),
            "row_index": _safe_int(row.get("row_index")),
            "source_name": str(extra.get("source_filename") or "").strip(),
        }
        slot = grouped.get(field)
        if slot is None:
            snippet = (
                f"{row_ref['source_name'] or 'archivo económico'}"
                f" | hoja {row_ref['sheet_name'] or 'N/D'}"
                f" | fila {row_ref['row_index'] or 'N/D'}"
                f" | {str(row.get('concepto_raw') or row.get('concepto_norm') or '').strip()}"
            ).strip()
            slot = {
                "field": field,
                "label": label,
                "concept_label": concept_label,
                "slot_type": str(extra.get("template_kind") or "").strip(),
                "sheet_name": row_ref["sheet_name"],
                "row_index": row_ref["row_index"],
                "source_name": row_ref["source_name"] or "anexo_economico.xlsx",
                "price_column_header": str(extra.get("price_column_header") or "").strip(),
                "context_snippet": snippet[:420],
                "rows_count": 0,
                "quantity_total": 0.0,
                "rows": [],
                "zone": str(extra.get("zone") or "").strip().upper() or None,
                "schedule": str(extra.get("schedule") or "").strip() or None,
                "unit": str(row.get("unidad") or "").strip() or None,
            }
            if str(extra.get("template_kind") or "").strip() == "monthly_material_requirement":
                support = material_support_map.get(_norm_text(_concept_text(row)))
                if support:
                    slot["quantity_support_source_name"] = support.get("source_name")
                    slot["quantity_support_sheet_name"] = support.get("sheet_name")
                    slot["quantity_support_row_index"] = support.get("row_index")
            grouped[field] = slot
        slot["rows_count"] += 1
        slot["quantity_total"] = round(float(slot.get("quantity_total") or 0.0) + qty, 4)
        slot["rows"].append(row_ref)

    slots = list(grouped.values())
    for slot in slots:
        slot["captured_price"] = _resolve_slot_price(slot, concept_prices or {})

    def _sort_key(slot: Dict[str, Any]) -> Tuple[int, str, str]:
        slot_type = str(slot.get("slot_type") or "")
        if slot_type == "service_zone_elements":
            order = 0
        elif slot_type == "location_price_grid":
            order = 1
        else:
            order = 2
        return order, str(slot.get("zone") or ""), _norm_text(slot.get("concept_label"))

    return sorted(slots, key=_sort_key)


def apply_structured_price_inputs(
    rows: List[Dict[str, Any]],
    concept_prices: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Aplica precios capturados por chat a renglones estructurados sin persistirlos."""
    slots = build_structured_price_slots(rows, concept_prices or {})
    price_by_field = {
        str(slot.get("field") or ""): float(slot.get("captured_price"))
        for slot in slots
        if slot.get("captured_price") is not None
    }
    if not price_by_field:
        return list(rows or [])

    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            out.append(row)
            continue
        sig = _slot_signature(row)
        if not sig:
            out.append(row)
            continue
        field, concept_label = sig
        if field not in price_by_field:
            out.append(row)
            continue
        updated = dict(row)
        extra = dict(_row_extra(row))
        updated["precio_unitario"] = price_by_field[field]
        extra["price_input_applied"] = True
        extra["price_input_field"] = field
        extra["price_input_label"] = concept_label
        extra["price_input_source"] = "economic_user_inputs"
        updated["extra"] = extra
        out.append(updated)
    return out
