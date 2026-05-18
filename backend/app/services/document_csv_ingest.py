"""
Ingesta CSV compartida: markdown para RAG + partidas estructuradas + normalización canónica.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from app.memory.repository import MemoryRepository
from app.services.tabular_line_item_extract import extract_line_items_from_csv_path
from app.services.economic_normalizer import normalize_line_items, merge_normalized_payload


async def process_csv_document(
    memory: MemoryRepository,
    session_id: str,
    doc_id: str,
    file_path: str,
    filename: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Construye payload equivalente a OCR para CSV y persiste partidas + normalizado canónico.
    """
    # Leer para construir contexto markdown simple (RAG-friendly)
    df = None
    for kwargs in (
        {"sep": None, "engine": "python", "encoding": "utf-8"},
        {"sep": ";", "engine": "python", "encoding": "utf-8"},
        {"sep": ",", "engine": "python", "encoding": "utf-8"},
        {"sep": None, "engine": "python", "encoding": "latin-1"},
    ):
        try:
            df = pd.read_csv(file_path, **kwargs)
            break
        except Exception:
            continue
    if df is None:
        raise ValueError(f"No se pudo leer CSV: {filename}")

    df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
    md_table = df.to_markdown(index=False) if not df.empty else "(CSV vacío tras limpieza)"
    csv_content = f"### ARCHIVO: {filename} | TABLA CSV\nCONTENIDO TABULAR:\n{md_table}"

    rows = extract_line_items_from_csv_path(file_path, filename)
    await memory.replace_line_items_for_document(session_id, doc_id, rows)

    try:
        session_state = await memory.get_session(session_id) or {}
        normalized = normalize_line_items(
            session_id=session_id,
            doc_id=doc_id,
            source_filename=filename,
            source_type="csv",
            rows=rows,
            raw_text=csv_content,
        )
        updated_state = merge_normalized_payload(session_state, normalized)
        await memory.save_session(session_id, updated_state)
    except Exception:
        pass

    ocr_result: Dict[str, Any] = {
        "extracted_text": csv_content,
        "pages": [{"page": "csv", "text": csv_content}],
        "total_pages": 1,
        "success": True,
    }
    return ocr_result, rows

