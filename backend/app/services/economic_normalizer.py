"""
Normalización canónica de datos económicos para fuentes tabulares.

Convierte `session_line_items` (u otras filas tabulares) en una estructura única
`economic_normalized_data` para consumo por EconomicAgent, RAG y validaciones.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_text(value: Any) -> str:
    t = re.sub(r"[^a-z0-9áéíóúñü\s]+", " ", str(value or "").strip().lower())
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify_category(concepto: str) -> str:
    """Clasifica una fila económica a categoría canónica."""
    t = _norm_text(concepto)
    if any(k in t for k in ("salario", "operador", "guardia", "elemento", "mano de obra")):
        return "mano_obra"
    if any(k in t for k in ("aguinaldo", "vacaciones", "prima vacacional", "prestacion")):
        return "prestaciones"
    if re.search(r"\bi\s*m\s*s\s*s\b", t):
        return "imss"
    if any(k in t for k in ("imss", "enfermedad", "invalidez", "cesantia", "riesgo de trabajo", "guarderias")):
        return "imss"
    if any(k in t for k in ("infonavit", "sar", "impuesto", "sobre nomina", "isn")):
        return "impuestos"
    if any(k in t for k in ("indirecto", "administracion", "utilidad", "margen")):
        return "indirectos_utilidad"
    if any(k in t for k in ("subtotal", "total", "gran total", "salario integrado")):
        return "agregado"
    return "otro"


def normalize_line_items(
    *,
    session_id: str,
    doc_id: str,
    source_filename: str,
    source_type: str,
    rows: List[Dict[str, Any]],
    raw_text: str = "",
) -> Dict[str, Any]:
    """
    Produce payload canónico por documento.

    Nota: en esta fase se normaliza y clasifica; la inferencia avanzada queda para Sprint 2.
    """
    items: List[Dict[str, Any]] = []
    category_totals: Dict[str, float] = {}
    total_detected = 0.0
    total_items = 0

    zero_like_count = 0
    numeric_rows_seen = 0

    for r in rows or []:
        concepto = str(r.get("concepto_raw") or r.get("concepto_norm") or "").strip()
        if not concepto:
            continue
        categoria = classify_category(concepto)
        precio_unitario = float(r.get("precio_unitario") or 0.0)
        numeric_rows_seen += 1
        if abs(precio_unitario) < 1e-6 or precio_unitario <= 0.0001:
            zero_like_count += 1
        cantidad = r.get("cantidad")
        try:
            cantidad_f = float(cantidad) if cantidad is not None else None
        except (TypeError, ValueError):
            cantidad_f = None
        subtotal = (cantidad_f * precio_unitario) if cantidad_f is not None else precio_unitario

        item = {
            "line_item_id": r.get("id"),
            "concepto": concepto,
            "concepto_norm": r.get("concepto_norm") or _norm_text(concepto),
            "categoria": categoria,
            "cantidad": cantidad_f,
            "unidad": r.get("unidad"),
            "factor": None,
            "precio_unitario": precio_unitario,
            "subtotal": subtotal,
            "moneda": r.get("moneda") or "MXN",
            "periodicidad": "mensual",
            "confidence": 0.72,
            "metadata_desglose": {
                "origen_captura": "document_tabular",
                "naturaleza_valor": "capturado",
                "categoria_inferida_por": "regla_textual",
            },
            "source": {
                "source_type": source_type,
                "doc_id": doc_id,
                "sheet_name": r.get("sheet_name"),
                "row_index": r.get("row_index"),
            },
        }
        items.append(item)
        total_items += 1
        category_totals[categoria] = round(category_totals.get(categoria, 0.0) + subtotal, 2)

    # --- Bloque 2 (inferencia semántica inicial) ---
    # Si hay filas "agregado" (subtotal/total/salario integrado) que son coherentes
    # con la suma de partidas base, evitamos doble conteo en total_detected.
    non_aggregate_total = sum(float(i.get("subtotal") or 0.0) for i in items if i.get("categoria") != "agregado")
    aggregate_items = [i for i in items if i.get("categoria") == "agregado"]
    aggregate_values = [float(i.get("subtotal") or 0.0) for i in aggregate_items]
    aggregate_max = max(aggregate_values) if aggregate_values else 0.0
    has_aggregates = bool(aggregate_values)

    # Tolerancia híbrida (absoluta + relativa) para tablas de costos reales.
    tol_abs = 10.0
    tol_rel = 0.005  # 0.5%
    tol = max(tol_abs, abs(non_aggregate_total) * tol_rel)
    aggregate_matches_base = has_aggregates and abs(aggregate_max - non_aggregate_total) <= tol

    # Heurística: "salario integrado" suele ser subtotal intermedio, no el total final de propuesta.
    aggregate_kinds = []
    for ai in aggregate_items:
        c = _norm_text(ai.get("concepto"))
        kind = "aggregate_other"
        if "salario integrado" in c:
            kind = "subtotal_intermedio_salario_integrado"
        elif "subtotal" in c:
            kind = "subtotal_intermedio"
        elif "total" in c or "gran total" in c:
            kind = "total_declarado"
        aggregate_kinds.append(
            {
                "concepto": ai.get("concepto"),
                "subtotal": float(ai.get("subtotal") or 0.0),
                "kind": kind,
            }
        )

    if aggregate_matches_base:
        total_detected = non_aggregate_total
        total_strategy = "base_without_aggregates"
    else:
        # Fallback conservador: elegir el mayor entre base y agregado declarado
        # evita sobreestimación por doble conteo (base + total declarado).
        total_detected = max(non_aggregate_total, aggregate_max)
        total_strategy = "max_base_vs_aggregate"

    # Señales de placeholder comunes (ej. TOTAL 0.00 en plantillas sin cantidad).
    norm_raw = _norm_text(raw_text)
    zero_ratio = (zero_like_count / numeric_rows_seen) if numeric_rows_seen > 0 else 0.0
    placeholder_signals = {
        "raw_text_contains_total_0": bool(re.search(r"(?i)\btotal\b[^\n\r]{0,30}\$?\s*0(?:[.,]0+)?", raw_text or "")),
        "raw_text_contains_cantidad_elementos": "cantidad de elementos" in norm_raw,
        "raw_text_contains_pending_markers": any(
            m in norm_raw for m in ("[pendiente]", " n/a ", " no aplica ", " -$ ", " 0 0001 ")
        ),
        "high_zero_ratio": zero_ratio >= 0.8 and numeric_rows_seen >= 5,
        "zero_ratio": round(zero_ratio, 3),
    }

    return {
        "schema_version": "1.0.0",
        "session_id": session_id,
        "document_id": doc_id,
        "source_filename": source_filename,
        "source_type": source_type,
        "normalized_items": items,
        "summary": {
            "items_count": total_items,
            "total_detected": round(total_detected, 2),
            "category_totals": category_totals,
            "placeholder_signals": placeholder_signals,
            "inference": {
                "has_aggregates": has_aggregates,
                "aggregate_max": round(aggregate_max, 2),
                "non_aggregate_total": round(non_aggregate_total, 2),
                "aggregate_matches_base": bool(aggregate_matches_base),
                "total_strategy": total_strategy,
                "tolerance_used": round(tol, 2),
                "aggregate_kinds": aggregate_kinds,
            },
            "is_placeholder_template": bool(
                placeholder_signals.get("raw_text_contains_pending_markers")
                or placeholder_signals.get("high_zero_ratio")
            ),
        },
        "created_at": _utc_iso_now(),
    }


def merge_normalized_payload(
    session_state: Dict[str, Any],
    normalized_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Inserta/actualiza payload canónico por documento dentro de session_state."""
    state = dict(session_state or {})
    root = dict(state.get("economic_normalized_data") or {})
    docs = dict(root.get("documents") or {})

    doc_id = str(normalized_payload.get("document_id") or "")
    if not doc_id:
        return state
    docs[doc_id] = normalized_payload

    # Recalcular resumen agregado de sesión
    total_docs = 0
    total_items = 0
    total_amount = 0.0
    category_totals: Dict[str, float] = {}
    for payload in docs.values():
        if not isinstance(payload, dict):
            continue
        total_docs += 1
        summ = payload.get("summary") or {}
        total_items += int(summ.get("items_count") or 0)
        total_amount += float(summ.get("total_detected") or 0.0)
        ct = summ.get("category_totals") or {}
        if isinstance(ct, dict):
            for k, v in ct.items():
                try:
                    category_totals[k] = round(category_totals.get(k, 0.0) + float(v), 2)
                except (TypeError, ValueError):
                    continue

    root["documents"] = docs
    root["summary"] = {
        "documents_count": total_docs,
        "items_count": total_items,
        "total_detected": round(total_amount, 2),
        "category_totals": category_totals,
        "updated_at": _utc_iso_now(),
    }
    root["schema_version"] = "1.0.0"
    state["economic_normalized_data"] = root
    return state

