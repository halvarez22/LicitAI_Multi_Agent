"""
Sincroniza pendientes económicos tras ingestar tablas (Excel/DOCX) con precios en sesión.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.memory.repository import MemoryRepository


def is_reliable_pricing_row(row: Dict[str, Any]) -> bool:
    """Filtra filas tabulares que sí pueden usarse como evidencia económica (regla del motor)."""
    if not isinstance(row, dict):
        return False
    try:
        price = float(row.get("precio_unitario") or 0.0)
    except (TypeError, ValueError):
        return False
    if price <= 0:
        return False

    extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
    if str(extra.get("layout") or "").strip().lower() == "raw_calculation":
        return False

    col_idx = extra.get("price_column_index")
    if col_idx is None:
        source_filename = str(extra.get("source_filename") or "").strip().lower()
        if source_filename.endswith((".xlsx", ".xls")):
            return False
        return True
    try:
        return int(float(col_idx)) >= 0
    except (TypeError, ValueError):
        return False


def _is_price_source_pending(question: Dict[str, Any]) -> bool:
    """True si el pendiente pide la fuente genérica de precios (no un precio unitario)."""
    if not isinstance(question, dict):
        return False
    if str(question.get("field") or "").strip() == "economic_price_source":
        return True
    if str(question.get("input_mode") or "").strip().lower() == "price_source":
        return True
    if (
        str(question.get("type") or "").strip() == "economic_validation_blocking"
        and str(question.get("input_mode") or "").strip().lower() == "price_source"
    ):
        return True
    return False


def filter_reliable_pricing_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filas tabulares con precio unitario utilizable."""
    return [row for row in (rows or []) if is_reliable_pricing_row(row)]


_MIN_CALCULATION_BREAKDOWN_ROWS = 2


def _row_positive_price(row: Dict[str, Any]) -> bool:
    """True si la fila tiene precio unitario numérico estrictamente positivo."""
    if not isinstance(row, dict):
        return False
    try:
        return float(row.get("precio_unitario") or 0.0) > 0
    except (TypeError, ValueError):
        return False


def _has_calculation_breakdown_evidence(rows: List[Dict[str, Any]]) -> bool:
    """
    Desglose tipo integración de costos (Anexo 8): varias filas ``raw_calculation`` con precio.

    Requiere al menos dos filas para evitar falsos positivos por una celda suelta.
    """
    priced_raw = 0
    for row in rows or []:
        if not _row_positive_price(row):
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if str(extra.get("layout") or "").strip().lower() == "raw_calculation":
            priced_raw += 1
            if priced_raw >= _MIN_CALCULATION_BREAKDOWN_ROWS:
                return True
    return False


def has_price_source_tabular_evidence(rows: List[Dict[str, Any]]) -> bool:
    """
    True si hay evidencia tabular suficiente para cerrar ``economic_price_source``.

    Capa A (chat): catálogo/partida estructurada **o** desglose de cálculo con >=2 filas.
    No relaja ``is_reliable_pricing_row`` (capa B / anclaje estricto en EconomicAgent).
    """
    if filter_reliable_pricing_rows(rows):
        return True
    return _has_calculation_breakdown_evidence(rows)


async def sync_economic_pending_after_tabular_ingest(
    memory: MemoryRepository,
    session_id: str,
) -> Dict[str, Any]:
    """
    Cierra ``economic_price_source`` si la sesión ya tiene precios tabulares auditables.

    Returns:
        Dict con ``cleared_price_source``, ``reliable_count`` y ``refreshed_validations``.
    """
    out: Dict[str, Any] = {
        "cleared_price_source": False,
        "reliable_count": 0,
        "refreshed_validations": False,
    }
    try:
        rows = await memory.get_line_items_for_session(session_id) or []
    except Exception:
        rows = []

    reliable = filter_reliable_pricing_rows(rows)
    out["reliable_count"] = len(reliable)
    if not has_price_source_tabular_evidence(rows):
        return out

    session_state = await memory.get_session(session_id) or {}
    pending = list(session_state.get("pending_questions") or [])
    new_pending = [q for q in pending if not _is_price_source_pending(q)]
    if len(new_pending) != len(pending):
        session_state["pending_questions"] = new_pending
        session_state["current_question_index"] = 0
        await memory.save_session(session_id, session_state)
        out["cleared_price_source"] = True

    try:
        from app.economic_validation.service import refresh_economic_validations_for_session

        await refresh_economic_validations_for_session(memory, session_id)
        out["refreshed_validations"] = True
    except Exception:
        pass

    return out


def tech_requirements_from_tabular_pricing(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convierte partidas con precio en requisitos técnicos mínimos para el motor económico."""
    reqs: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or f"tabular_{idx}")
        label = str(
            row.get("concepto_raw") or row.get("concepto_norm") or f"Partida {idx}"
        ).strip()
        reqs.append(
            {
                "id": cid,
                "descripcion": label,
                "label": label,
                "origen": "session_line_items",
            }
        )
    return reqs
