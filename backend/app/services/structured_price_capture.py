"""
Encolado unificado de captura de precios estructurados (matriz vs uno por uno).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.config import settings as app_settings
from app.services.chat_economic_matrix import (
    build_proactive_economic_matrix_welcome,
    should_use_matrix_capture,
)
from app.services.economic_capture_matrix_service import build_capture_matrix_blocks


def prepare_structured_price_capture(
    session_state: Dict[str, Any],
    missing_slots: List[Dict[str, Any]],
    *,
    session_id: str,
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """
    Devuelve (pending_questions, intro_message, session_updates).

    Si hay suficientes slots, activa modo matriz (una sola pregunta + bloques en sesión).
    """
    line_items = list(session_state.get("session_line_items") or [])
    concept_prices = session_state.get("economic_user_inputs") or {}
    matrices = build_capture_matrix_blocks(line_items, concept_prices)
    total = len(missing_slots or [])
    updates: Dict[str, Any] = {
        "structured_price_pending_count": total,
    }
    if matrices:
        updates["capture_matrix_blocks"] = matrices

    if should_use_matrix_capture(
        total,
        session_mode=str(session_state.get("economic_capture_mode") or "matrix"),
    ) and matrices:
        updates["economic_capture_mode"] = "matrix"
        support_name = next(
            (
                str(slot.get("quantity_support_source_name") or "").strip()
                for slot in (missing_slots or [])
                if str(slot.get("quantity_support_source_name") or "").strip()
            ),
            "",
        )
        if support_name:
            updates["structured_price_support_name"] = support_name
        intro = build_proactive_economic_matrix_welcome(
            matrices,
            pending_row_count=total,
            support_name=support_name,
        )
        pending = [
            {
                "type": "economic_price_matrix",
                "field": "economic_matrix_bulk",
                "label": "Matriz de precios unitarios",
                "question": intro,
                "blocking": True,
                "matrix_block_count": len(matrices),
                "matrix_row_count": sum(
                    len(b.get("matrix_rows") or []) for b in matrices
                ),
            }
        ]
        return pending, intro, updates

    block_group_key = None
    min_block = max(1, int(getattr(app_settings, "BLOCK_RESOLUTION_MIN_ITEMS", 3) or 3))
    if total >= min_block:
        block_group_key = f"economic_structured:{session_id}"
    updates["economic_capture_mode"] = "one_by_one"
    from app.agents.economic import (
        _build_structured_price_intro,
        _build_structured_price_pending_questions,
    )

    pending = _build_structured_price_pending_questions(
        missing_slots,
        block_group_key=block_group_key,
    )
    intro = _build_structured_price_intro(missing_slots)
    return pending, intro, updates
