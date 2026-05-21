from app.core.logging_config import get_logger
import fitz  # PyMuPDF
import os, logging
from typing import Any, Dict, List

logger = get_logger(__name__)


def _format_table_as_markdown(table: Any) -> str:
    """Formatea una tabla PyMuPDF como markdown con separadores de columna.

    Itera las filas retornadas por ``table.extract()``, convierte cada celda a
    ``str`` y aplica ``.strip()``. La primera fila se usa como encabezado, la
    segunda como separador ``---`` y el resto como cuerpo de la tabla.

    Args:
        table: Objeto tabla retornado por ``page.find_tables()`` de PyMuPDF.

    Returns:
        String con la tabla en formato markdown. Retorna cadena vacía si la
        tabla no contiene filas.
    """
    rows: List[str] = []
    for row in table.extract():
        cells = [str(cell if cell is not None else "").strip() for cell in row]
        rows.append(" | ".join(cells))

    if not rows:
        return ""

    header = rows[0]
    col_count = len(header.split(" | "))
    separator = " | ".join(["---"] * col_count)
    body = "\n".join(rows[1:]) if len(rows) > 1 else ""

    parts = [header, separator]
    if body:
        parts.append(body)
    return "\n".join(parts)


class DigitalExtractorAgent:
    """
    Agente especialista en extracción de texto nativo (Vía Rápida).
    Utiliza PyMuPDF para obtener información textual de documentos no escaneados.
    Es de alto rendimiento y bajo consumo de recursos (100% CPU).
    """

    def __init__(self):
        self.name = "DigitalExtractorAgent"

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Extrae el texto de un PDF digital.
        
        Args:
            file_path: Ruta absoluta al archivo PDF.
            
        Returns:
            Dict con el texto extraído, lista de páginas y bandera de éxito.
            Si el documento tiene menos de 100 caracteres, devuelve success: False 
            indicando que probablemente requiere OCR (Vision).
        """
        logger.info(f"[{self.name}] Iniciando escaneo de texto nativo: {file_path}")
        
        if not os.path.exists(file_path):
            logger.error(f"[{self.name}] Archivo no encontrado: {file_path}")
            return {"error": f"Archivo no encontrado: {file_path}", "success": False}
            
        try:
            doc = fitz.open(file_path)
            full_text = ""
            extracted_pages = []

            real_text_chars = 0
            for i, page in enumerate(doc):
                page_text = self.extract_page_digital(page)
                extracted_pages.append({"page": i + 1, "text": page_text})
                full_text += f"\n--- PÁGINA {i+1} ---\n{page_text}\n"
                real_text_chars += len(page_text)
                
            # Criterio de Éxito: Más de 100 caracteres significativos.
            if real_text_chars > 100:
                logger.info(f"[{self.name}] Extraccion digital exitosa ({real_text_chars} caracteres)")
                return {
                    "total_pages": len(doc),
                    "extracted_text": full_text.strip(),
                    "pages": extracted_pages,
                    "method": "pymupdf_digital",
                    "success": True
                }
            else:
                logger.info(f"[{self.name}] Documento detectado como escaneado ({real_text_chars} chars). Requiere OCR.")
                return {"success": False, "reason": "scanned_document"}
                
        except Exception as e:
            logger.error(f"[{self.name}] Error critico en extraccion digital: {str(e)}")
            return {"error": str(e), "success": False}

    def extract_page_digital(self, page: fitz.Page) -> str:
        """Extrae el texto digital de una página individual con formateo de tablas."""
        table_blocks: List[str] = []
        table_rects = []
        try:
            tables = list(page.find_tables())
            for tbl in tables:
                md = _format_table_as_markdown(tbl)
                if md.strip():
                    table_blocks.append(md)
                    table_rects.append(tbl.bbox)
        except Exception as exc:
            logger.warning(
                "pdf_table_extraction_failed",
                page=page.number + 1,
                error=str(exc),
            )

        # Extraer texto plano excluyendo áreas de tablas con markdown exitoso
        blocks = page.get_text("blocks")
        plain_text_parts = []
        for b in blocks:
            block_rect = fitz.Rect(b[:4])
            is_inside_table = any(
                block_rect.intersect(t_rect).get_area() > (block_rect.get_area() * 0.5) 
                for t_rect in table_rects
            )
            if not is_inside_table:
                plain_text_parts.append(b[4].strip())
        
        plain_text = "\n".join(p for p in plain_text_parts if p)
        page_parts = table_blocks + ([plain_text] if plain_text else [])
        return "\n\n".join(page_parts)

