"""
Construye bloques de captura tipo matriz (archivo × columna × filas) — Ítem D.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.economic_column_roles import (
    ROLE_UNIT_PRICE_EXCL_IVA,
    ROLE_UNIT_PRICE_IVA_INCLUDED,
    detect_column_role,
    human_role_label,
)
from app.services.structured_economic_price_mapper import build_structured_price_slots

MATRIX_CAPTURE_MIN_ITEMS = 5
CAPTURE_MATRIX_META_SCHEMA = "1.0.0"

_CHANNEL_BADGES = {
    "detected": "detectado",
    "user_tsv": "pegado chat",
    "user_csv": "import csv",
    "user_block": "bloque ui",
    "user_direct": "usuario",
}

_ECON_PENDING_TYPES = frozenset(
    {"economic_price", "economic_price_matrix", "economic_validation_blocking"}
)

_META_ECON_INPUT_KEYS = frozenset(
    {
        "allow_zero_total_base_ack",
        "economic_matrix_bulk",
    }
)


def _count_filled_price_inputs(inputs: Dict[str, Any]) -> int:
    """Precios unitarios ya capturados (excluye metadatos de sesión)."""
    n = 0
    for key, val in inputs.items():
        if str(key) in _META_ECON_INPUT_KEYS:
            continue
        if val is None or str(val).strip() == "":
            continue
        try:
            float(str(val).replace(",", "").replace("$", ""))
            n += 1
        except (TypeError, ValueError):
            continue
    return n


def economic_capture_status(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resumen de cobertura de precios (matriz + ``economic_user_inputs``).
    """
    blocks = session_state.get("capture_matrix_blocks") or []
    inputs = session_state.get("economic_user_inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    fields: List[str] = []
    for block in blocks:
        for row in block.get("matrix_rows") or []:
            if not isinstance(row, dict):
                continue
            field = str(row.get("field") or "").strip()
            if field:
                fields.append(field)
    total = len(fields)
    filled = sum(
        1
        for f in fields
        if f in inputs and inputs[f] is not None and str(inputs[f]).strip() != ""
    )
    pending_eco = sum(
        1
        for q in (session_state.get("pending_questions") or [])
        if str(q.get("type") or "") in _ECON_PENDING_TYPES
    )
    inputs_only = total == 0 and _count_filled_price_inputs(inputs) >= MATRIX_CAPTURE_MIN_ITEMS
    if inputs_only:
        filled = _count_filled_price_inputs(inputs)
        total = filled
    missing = max(0, total - filled)
    tolerance = 2
    capture_complete = pending_eco == 0 and (
        (total > 0 and filled >= max(1, total - tolerance))
        or (inputs_only and filled >= MATRIX_CAPTURE_MIN_ITEMS)
    )
    return {
        "total": total,
        "filled": filled,
        "missing": missing,
        "pending_economic": pending_eco,
        "capture_complete": capture_complete,
    }


def build_cell_provenance_ui(
    *,
    source_file: str,
    sheet_name: Optional[str] = None,
    row_index: Optional[int] = None,
    col_index: Optional[int] = None,
    column_role: Optional[str] = None,
    channel: str = "detected",
    filled: bool = False,
) -> Dict[str, Any]:
    """
    Procedencia auditable por celda (estándar HITL — Ítem D.13).

    ``channel``: detected | user_tsv | user_csv | user_block | user_direct
    """
    role = str(column_role or ROLE_UNIT_PRICE_EXCL_IVA)
    badge = _CHANNEL_BADGES.get(channel, channel)
    return {
        "source": channel if channel.startswith("user") else "document_detected",
        "channel": channel,
        "badge": badge,
        "label": human_role_label(role),
        "source_file": str(source_file or "").strip()[:255],
        "sheet": str(sheet_name or "").strip()[:128] or None,
        "row": int(row_index) if row_index is not None else None,
        "col": int(col_index) if col_index is not None else None,
        "column_role": role,
        "filled": bool(filled),
    }


def attach_provenance_to_matrix_blocks(
    blocks: List[Dict[str, Any]],
    *,
    economic_user_inputs: Optional[Dict[str, Any]] = None,
    default_channel: str = "detected",
) -> List[Dict[str, Any]]:
    """Añade ``provenance_ui`` a cada fila de matriz para API y paneles."""
    inputs = economic_user_inputs if isinstance(economic_user_inputs, dict) else {}
    out: List[Dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        nb = dict(block)
        source = str(block.get("source_file") or "")
        role = str(block.get("column_role") or ROLE_UNIT_PRICE_EXCL_IVA)
        price_col_idx = block.get("price_column_index")
        rows_out: List[Dict[str, Any]] = []
        for row in block.get("matrix_rows") or []:
            if not isinstance(row, dict):
                continue
            nr = dict(row)
            field = str(nr.get("field") or "").strip()
            filled = bool(field and field in inputs and str(inputs.get(field) or "").strip() != "")
            channel = str(nr.get("capture_channel") or default_channel)
            nr["provenance_ui"] = build_cell_provenance_ui(
                source_file=source,
                sheet_name=nr.get("sheet_name"),
                row_index=nr.get("row_index"),
                col_index=nr.get("price_column_index") or price_col_idx,
                column_role=role,
                channel=channel,
                filled=filled,
            )
            rows_out.append(nr)
        nb["matrix_rows"] = rows_out
        out.append(nb)
    return out


def build_capture_matrix_meta(
    blocks: List[Dict[str, Any]],
    line_items: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Layout detectado versionado en sesión (Ítem D.4).

    Resume archivos, roles de columna y dimensión de fila sin hardcode por licitación.
    """
    layouts: List[Dict[str, Any]] = []
    template_kinds: set[str] = set()
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        rows = block.get("matrix_rows") or []
        if any("|" in str(r.get("label") or "") for r in rows):
            dim = "zona_horario"
        elif block.get("column_role") == ROLE_UNIT_PRICE_IVA_INCLUDED:
            dim = "localidades"
        else:
            dim = "conceptos"
        layouts.append(
            {
                "source_file": block.get("source_file"),
                "column_role": block.get("column_role"),
                "column_label": block.get("column_label"),
                "row_dimension": dim,
                "row_count": len(rows),
                "block_group_key": block.get("block_group_key"),
            }
        )
    for row in line_items or []:
        if not isinstance(row, dict):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        tk = str(extra.get("template_kind") or "").strip()
        if tk:
            template_kinds.add(tk)
    return {
        "schema_version": CAPTURE_MATRIX_META_SCHEMA,
        "block_count": len(blocks or []),
        "total_rows": sum(len(b.get("matrix_rows") or []) for b in (blocks or []) if isinstance(b, dict)),
        "template_kinds": sorted(template_kinds),
        "layouts": layouts,
    }


def format_capture_summary_message(status: Dict[str, Any]) -> str:
    """Resumen unificado «capturaste X de Y» (Ítem D.12)."""
    filled = int(status.get("filled") or 0)
    total = int(status.get("total") or 0)
    if total <= 0:
        return "Aún no hay filas de precio detectadas en la matriz."
    if status.get("capture_complete"):
        return (
            f"Capturaste **{filled}** de **{total}** precio(s) unitario(s). "
            "La cotización está lista para generar la propuesta económica."
        )
    missing = max(0, total - filled)
    return (
        f"Capturaste **{filled}** de **{total}** precio(s) unitario(s). "
        f"Faltan **{missing}** por completar."
    )


def hydrate_matrix_blocks_with_inputs(
    blocks: List[Dict[str, Any]],
    economic_user_inputs: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Refleja precios ya capturados en ``matrix_rows[].price`` para UI y bloques."""
    inputs = economic_user_inputs if isinstance(economic_user_inputs, dict) else {}
    out: List[Dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict):
            continue
        nb = dict(block)
        rows: List[Dict[str, Any]] = []
        for row in block.get("matrix_rows") or []:
            if not isinstance(row, dict):
                continue
            nr = dict(row)
            field = str(nr.get("field") or "").strip()
            if field and field in inputs:
                nr["price"] = inputs[field]
            rows.append(nr)
        nb["matrix_rows"] = rows
        out.append(nb)
    return attach_provenance_to_matrix_blocks(out, economic_user_inputs=inputs)


def build_capture_matrix_blocks_from_pending(
    pending: List[Dict[str, Any]],
    concept_prices: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Reconstruye matriz desde ``pending_questions`` ya encoladas (sesiones en vuelo).
    """
    econ = [q for q in (pending or []) if str(q.get("type") or "") == "economic_price"]
    if len(econ) < MATRIX_CAPTURE_MIN_ITEMS:
        return []

    groups: Dict[str, Dict[str, Any]] = {}
    prices = concept_prices if isinstance(concept_prices, dict) else {}
    for q in econ:
        oi = q.get("original_item") if isinstance(q.get("original_item"), dict) else {}
        source = str(oi.get("source") or q.get("document_hint") or "anexo_economico.xlsx")
        field = str(q.get("field") or "").strip()
        label = str(q.get("label") or "").replace("Precio (sin IVA): ", "").strip()
        if not field:
            continue
        gkey = source
        bucket = groups.setdefault(
            gkey,
            {
                "source_file": source,
                "column_label": "Precio unitario (sin IVA)",
                "rows": [],
            },
        )
        captured = prices.get(field)
        bucket["rows"].append(
            {
                "field": field,
                "label": label,
                "price": "" if captured is None else str(captured),
            }
        )

    blocks: List[Dict[str, Any]] = []
    for bucket in groups.values():
        rows_meta = bucket.get("rows") or []
        if not rows_meta:
            continue
        bucket["block_group_key"] = f"matrix_pending_{hash(bucket['source_file']) & 0xFFFFFF:06x}"
        bucket["matrix_columns"] = [
            {"key": "label", "title": "Zona / horario / ubicación"},
            {"key": "price", "title": bucket["column_label"]},
        ]
        bucket["matrix_rows"] = [
            {
                "label": r.get("label"),
                "price": r.get("price", ""),
                "field": r.get("field"),
            }
            for r in rows_meta
        ]
        bucket["intro_message"] = (
            f"Precios unitarios para **{bucket['source_file']}** ({len(rows_meta)} filas)."
        )
        blocks.append(bucket)
    return blocks


def build_capture_matrix_blocks(
    rows: List[Dict[str, Any]],
    concept_prices: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Agrupa slots pendientes por (archivo, rol de columna) para InteractionBlock / chat.

    Retorna lista de dicts con ``matrix_rows``, ``intro_message``, metadata de procedencia.
    """
    slots = build_structured_price_slots(rows, concept_prices)
    pending = [s for s in slots if s.get("captured_price") is None]
    if not pending:
        return []

    groups: Dict[str, Dict[str, Any]] = {}
    for slot in pending:
        source = str(slot.get("source_name") or "anexo_economico.xlsx")
        header_hint = str(slot.get("price_column_header") or slot.get("label") or "")
        role = detect_column_role(header_hint) or ROLE_UNIT_PRICE_EXCL_IVA
        if role not in (ROLE_UNIT_PRICE_IVA_INCLUDED, ROLE_UNIT_PRICE_EXCL_IVA):
            role = ROLE_UNIT_PRICE_EXCL_IVA
        gkey = f"{source}|{role}"
        bucket = groups.setdefault(
            gkey,
            {
                "source_file": source,
                "column_role": role,
                "column_label": human_role_label(role),
                "block_group_key": f"matrix_{hash(gkey) & 0xFFFFFF:06x}",
                "rows": [],
            },
        )
        row_label = str(slot.get("concept_label") or slot.get("label") or "").strip()
        extra_rows = slot.get("rows") or []
        row_ref = extra_rows[0] if extra_rows and isinstance(extra_rows[0], dict) else {}
        bucket["rows"].append(
            {
                "field": slot.get("field"),
                "label": row_label,
                "sheet_name": slot.get("sheet_name") or row_ref.get("sheet_name"),
                "row_index": slot.get("row_index") or row_ref.get("row_index"),
                "price_column_index": slot.get("price_column_index"),
            }
        )

    blocks: List[Dict[str, Any]] = []
    for bucket in groups.values():
        rows_meta = bucket["rows"]
        if not rows_meta:
            continue
        dim = "localidades" if any("|" in str(r.get("label") or "") for r in rows_meta) else "conceptos"
        loc_list = ", ".join(str(r.get("label") or "")[:40] for r in rows_meta[:8])
        if len(rows_meta) > 8:
            loc_list += f" … (+{len(rows_meta) - 8} más)"
        bucket["intro_message"] = (
            f"Para la propuesta económica en **{bucket['source_file']}**, "
            f"necesito el **{bucket['column_label']}** para estas {dim}: {loc_list}."
        )
        bucket["matrix_columns"] = [
            {"key": "label", "title": "Ubicación / concepto"},
            {"key": "price", "title": bucket["column_label"]},
        ]
        bucket["matrix_rows"] = [
            {
                "label": r.get("label"),
                "price": "",
                "field": r.get("field"),
                "sheet_name": r.get("sheet_name"),
                "row_index": r.get("row_index"),
                "price_column_index": r.get("price_column_index"),
            }
            for r in rows_meta
        ]
        blocks.append(bucket)
    return attach_provenance_to_matrix_blocks(blocks)


def parse_tsv_price_block(
    text: str,
    field_by_label: Dict[str, str],
) -> Dict[str, str]:
    """
    Parsea pegado TSV/CSV: ``etiqueta<TAB>precio`` → ``{field: precio}``.
    """
    out: Dict[str, str] = {}
    norm_map = {str(k).strip().lower(): v for k, v in (field_by_label or {}).items()}
    for line in (text or "").strip().splitlines():
        parts = re.split(r"[\t,;]", line.strip(), maxsplit=1)
        if len(parts) < 2:
            continue
        label, price_raw = parts[0].strip(), parts[1].strip()
        if not price_raw:
            continue
        field = norm_map.get(label.lower())
        if field:
            out[field] = price_raw
    return out
