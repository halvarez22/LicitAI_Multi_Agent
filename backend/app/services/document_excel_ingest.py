"""
Ingesta Excel compartida: markdown para RAG + partidas estructuradas en session_line_items.
Usada por upload/process y por el job de orquestación en background.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from app.memory.repository import MemoryRepository
from app.services.tabular_line_item_extract import extract_line_items_from_excel_path
from app.services.economic_normalizer import normalize_line_items, merge_normalized_payload


def _sync_parse_excel(file_path: str, filename: str) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extracción síncrona pesada para ejecutar en un hilo."""
    ext = filename.lower().split('.')[-1]
    engine = 'xlrd' if ext == 'xls' else None
    
    try:
        xl = pd.ExcelFile(file_path, engine=engine)
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
        return full_text, pages, rows
    except Exception as e:
        # Si xlrd no está o falla, levantamos error para el router
        raise ValueError(f"Error procesando Excel ({ext}): {str(e)}")


async def process_excel_document(
    memory: MemoryRepository,
    session_id: str,
    doc_id: str,
    file_path: str,
    filename: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Construye el mismo payload de extracción que espera el indexador vectorial y persiste partidas.
    Ejecuta la carga pesada en un executor para no bloquear el event loop.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    
    try:
        full_text, pages, rows = await loop.run_in_executor(None, _sync_parse_excel, file_path, filename)
    except Exception as e:
        return {
            "extracted_text": "",
            "pages": [],
            "total_pages": 0,
            "success": False,
            "error": str(e)
        }, []

    await memory.replace_line_items_for_document(session_id, doc_id, rows)
    try:
        session_state = await memory.get_session(session_id) or {}
        normalized = normalize_line_items(
            session_id=session_id,
            doc_id=doc_id,
            source_filename=filename,
            source_type="excel",
            rows=rows,
            raw_text=full_text,
        )
        updated_state = merge_normalized_payload(session_state, normalized)
        await memory.save_session(session_id, updated_state)
    except Exception:
        # Hardening: no romper ingesta si falla normalización canónica.
        pass

    ocr_result: Dict[str, Any] = {
        "extracted_text": full_text,
        "pages": pages,
        "total_pages": len(pages),
        "success": True,
    }
    return ocr_result, rows
