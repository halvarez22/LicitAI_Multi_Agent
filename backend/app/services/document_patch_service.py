"""
Regeneración quirúrgica tras corrección de precios (Ítem B).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.services.document_traceability import safe_file_sha256
from app.services.excel_filling_service import ExcelFillingService
from app.services.structured_economic_price_mapper import (
    apply_structured_price_inputs,
    build_structured_price_slots,
)


def _field_from_slot(slot: Dict[str, Any]) -> str:
    return str(slot.get("field") or "").strip()


def resolve_impacted_deliverables(
    session_state: Dict[str, Any],
    price_field: str,
) -> List[Dict[str, Any]]:
    """
    Determina archivos de salida que dependen de un slot de precio.
    """
    price_field = str(price_field or "").strip()
    if not price_field:
        return []

    line_items = list(session_state.get("session_line_items") or [])
    concept_prices = dict(session_state.get("economic_user_inputs") or {})
    rows = apply_structured_price_inputs(line_items, concept_prices)
    slots = build_structured_price_slots(rows, concept_prices)
    target_slot = next((s for s in slots if _field_from_slot(s) == price_field), None)
    if not target_slot:
        return []

    source_names: Set[str] = {str(target_slot.get("source_name") or "")}
    impacted: List[Dict[str, Any]] = []
    for task in reversed(session_state.get("tasks_completed") or []):
        if not isinstance(task, dict):
            continue
        tname = str(task.get("task") or "")
        if "economic" not in tname.lower() and tname != "economic_writer":
            continue
        payload = task.get("result") or task.get("data") or {}
        if not isinstance(payload, dict):
            continue
        for doc in payload.get("documentos") or []:
            if not isinstance(doc, dict):
                continue
            src = str(doc.get("source_filename") or doc.get("nombre") or "")
            if src and (src in source_names or any(sn in src for sn in source_names if sn)):
                impacted.append(doc)
    return impacted


async def apply_price_correction(
    memory: Any,
    session_id: str,
    *,
    price_field: str,
    new_value: float,
    previous_value: Optional[float] = None,
    source: str = "chat_correction",
) -> Dict[str, Any]:
    """
    Persiste override, recalcula validaciones y rellena Excel impactados.
    """
    from app.economic_validation.service import refresh_economic_validations_for_session

    fresh = await memory.get_session(session_id) or {}
    inputs = dict(fresh.get("economic_user_inputs") or {})
    cp = inputs.get("concept_prices")
    if not isinstance(cp, dict):
        cp = {}
    old = previous_value
    if old is None:
        try:
            old = float(cp.get(price_field, inputs.get(price_field)))
        except (TypeError, ValueError):
            old = None
    if price_field in cp or price_field.startswith("concept_") or "partida" in price_field.lower():
        cp = dict(cp)
        cp[price_field] = new_value
        inputs["concept_prices"] = cp
    else:
        inputs[price_field] = new_value
    audit = list(fresh.get("price_correction_audit") or [])
    audit.append(
        {
            "field": price_field,
            "previous": old,
            "new": new_value,
            "source": source,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    fresh["economic_user_inputs"] = inputs
    fresh["price_correction_audit"] = audit[-100:]
    await memory.save_session(session_id, fresh)

    await refresh_economic_validations_for_session(memory, session_id)
    fresh = await memory.get_session(session_id) or fresh

    updated_paths: List[str] = []
    hash_delta: Dict[str, Dict[str, str]] = {}
    regen_paths: List[str] = []
    try:
        from app.services.economic_document_reapply import regenerate_all_economic_deliverables

        regen = await regenerate_all_economic_deliverables(memory, session_id)
        regen_paths = list(regen.get("updated") or [])
        for p in regen_paths:
            if p not in updated_paths:
                updated_paths.append(p)
            hash_delta[p] = {"previous": None, "current": safe_file_sha256(p)}
    except Exception:
        regen_paths = []

    line_items = list(fresh.get("session_line_items") or [])
    rows = apply_structured_price_inputs(line_items, inputs)
    filler = ExcelFillingService()

    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        field_meta = build_structured_price_slots([row], inputs)
        if not any(_field_from_slot(s) == price_field for s in field_meta):
            continue
        src = str(extra.get("source_filename") or "").strip()
        if not src:
            continue
        col = extra.get("price_column_index")
        if col is None:
            continue
        by_source.setdefault(src, []).append(
            {
                "sheet_name": row.get("sheet_name"),
                "row_index": row.get("row_index"),
                "price_column_index": col,
                "final_price": float(row.get("precio_unitario") or new_value),
                "quantity": float(row.get("cantidad") or 0) or None,
                "amount_column_index": extra.get("subtotal_column_index"),
                "quantity_column_index": extra.get("quantity_column_index"),
            }
        )

    for src, items in by_source.items():
        try:
            out_path = filler.fill_proposal_excel(
                session_id=session_id,
                source_filename=src,
                items_to_fill=items,
            )
            old_hash = None
            for doc in resolve_impacted_deliverables(fresh, price_field):
                if str(doc.get("ruta") or "") == out_path:
                    old_hash = doc.get("output_hash")
            new_hash = safe_file_sha256(out_path)
            updated_paths.append(out_path)
            hash_delta[out_path] = {"previous": old_hash, "current": new_hash}
        except Exception:
            continue

    patch_meta = {
        "price_field": price_field,
        "updated_files": updated_paths,
        "regenerated_economic": regen_paths,
        "hash_delta": hash_delta,
        "file_count": len(updated_paths),
    }
    fresh["last_document_patch"] = patch_meta
    await memory.save_session(session_id, {"last_document_patch": patch_meta})

    return patch_meta


def write_patch_manifest_delta(session_path: str, hash_delta: Dict[str, Dict[str, str]]) -> Optional[str]:
    """Escribe manifiesto delta junto a ``_compranet_validated`` si existe."""
    validated = os.path.join(session_path, "_compranet_validated")
    if not os.path.isdir(validated) or not hash_delta:
        return None
    manifest_path = os.path.join(validated, "MANIFIESTO_PATCH_DELTA.json")
    payload = {
        "schema": "1.0",
        "files": [
            {"path": path, **hashes} for path, hashes in hash_delta.items()
        ],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return manifest_path
