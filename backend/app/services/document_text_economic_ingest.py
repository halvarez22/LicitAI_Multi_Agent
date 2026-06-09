"""
Puente HRU: texto plano (PDF nativo/OCR, TXT) → session_line_items + economic_normalized_data.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.memory.repository import MemoryRepository
from app.services.economic_normalizer import merge_normalized_payload, normalize_line_items
from app.services.tabular_line_item_extract import extract_line_items_from_text_blob


async def persist_text_blob_economic_rows(
    memory: MemoryRepository,
    session_id: str,
    doc_id: str,
    extracted_text: str,
    filename: str,
    *,
    source_type: str,
) -> List[Dict[str, Any]]:
    """
    Extrae partidas cotizables de un blob de texto y las persiste en sesión.

    Returns:
        Filas materializadas (puede ser lista vacía si no hay señal tabular).
    """
    rows = extract_line_items_from_text_blob(extracted_text or "", filename)
    if not rows:
        return []

    await memory.replace_line_items_for_document(session_id, doc_id, rows)
    try:
        session_state = await memory.get_session(session_id) or {}
        normalized = normalize_line_items(
            session_id=session_id,
            doc_id=doc_id,
            source_filename=filename,
            source_type=source_type,
            rows=rows,
            raw_text=extracted_text or "",
        )
        updated_state = merge_normalized_payload(session_state, normalized)
        await memory.save_session(session_id, updated_state)
    except Exception:
        pass
    return rows
