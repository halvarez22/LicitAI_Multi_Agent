"""
Ingesta Excel compartida: markdown para RAG + partidas estructuradas en session_line_items.
Usada por upload/process y por el job de orquestación en background.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from app.memory.repository import MemoryRepository
from app.services.tabular_line_item_extract import extract_line_items_from_excel_path


async def process_excel_document(
    memory: MemoryRepository,
    session_id: str,
    doc_id: str,
    file_path: str,
    filename: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Construye el mismo payload de extracción que espera el indexador vectorial y persiste partidas.

    Returns:
        Tupla (ocr_result, filas_extraídas) donde ocr_result tiene keys extracted_text, pages, total_pages, success.
    """
    xl = pd.ExcelFile(file_path)
    full_text = ""
    pages: List[Dict[str, Any]] = []
    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)
        df = df.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if df.empty:
            continue
        md_table = df.to_markdown(index=False)
        sheet_content = f"### ARCHIVO: {filename} | HOJA: {sheet_name}\nCONTENIDO TABULAR:\n{md_table}"
        full_text += f"\n{sheet_content}\n"
        pages.append({"page": sheet_name, "text": sheet_content})

    rows = extract_line_items_from_excel_path(file_path, filename)
    await memory.replace_line_items_for_document(session_id, doc_id, rows)

    ocr_result: Dict[str, Any] = {
        "extracted_text": full_text,
        "pages": pages,
        "total_pages": len(pages),
        "success": True,
    }
    return ocr_result, rows
