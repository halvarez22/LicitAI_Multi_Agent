import fitz  # PyMuPDF
import os, logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

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
        print(f"[{self.name}] Iniciando escaneo de texto nativo: {file_path}")
        
        if not os.path.exists(file_path):
            logger.error(f"[{self.name}] Archivo no encontrado: {file_path}")
            return {"error": f"Archivo no encontrado: {file_path}", "success": False}
            
        try:
            doc = fitz.open(file_path)
            full_text = ""
            extracted_pages = []
            
            real_text_chars = 0
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                extracted_pages.append({"page": i+1, "text": text})
                full_text += f"\n--- PÁGINA {i+1} ---\n{text}\n"
                real_text_chars += len(text)
                
            # Criterio de Éxito: Más de 100 caracteres significativos.
            if real_text_chars > 100:
                print(f"[{self.name}] Extraccion digital exitosa ({real_text_chars} caracteres)")
                return {
                    "total_pages": len(doc),
                    "extracted_text": full_text.strip(),
                    "pages": extracted_pages,
                    "method": "pymupdf_digital",
                    "success": True
                }
            else:
                print(f"[{self.name}] Documento detectado como escaneado ({real_text_chars} chars). Requiere OCR.")
                return {"success": False, "reason": "scanned_document"}
                
        except Exception as e:
            logger.error(f"[{self.name}] Error critico en extraccion digital: {str(e)}")
            return {"error": str(e), "success": False}
