from app.core.logging_config import get_logger
import httpx
import os, logging
import gc
import asyncio
import base64
from io import BytesIO
from typing import Dict, Any, Optional
from pdf2image import pdfinfo_from_path, convert_from_path
import fitz  # PyMuPDF

logger = get_logger(__name__)

from app.utils.gpu_lock import VLM_SEMAPHORE, OllamaGuard

class VisionExtractorAgent:
    """
    Agente especialista en OCR avanzado vía VLM (Vision-Language Model).
    Utiliza GLM-OCR para extraer texto de documentos escaneados o imágenes.
    Requiere aceleración por GPU y gestiona el acceso mediante semáforos.
    """

    def __init__(self, ollama_url: Optional[str] = None):
        self.name = "VisionExtractorAgent"
        self.ollama_url = ollama_url or os.getenv("LLM_URL", os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"))

    def _get_total_pages_with_fallback(self, file_path: str) -> int:
        """
        Obtiene número de páginas sin depender únicamente de poppler.

        Prioriza ``pdfinfo_from_path``; si falla (entorno sin poppler),
        usa PyMuPDF como fallback determinista.
        """
        try:
            info = pdfinfo_from_path(file_path)
            return int(info["Pages"])
        except Exception as exc:
            logger.warning(
                "[%s] pdfinfo_from_path falló; usando fallback PyMuPDF. error=%s",
                self.name,
                str(exc),
            )
            with fitz.open(file_path) as doc:
                return int(doc.page_count)

    async def _render_page_base64(self, file_path: str, page_num: int) -> Optional[str]:
        """
        Renderiza una página PDF a JPEG base64.

        Estrategia:
        1) pdf2image/convert_from_path (rápido cuando poppler existe).
        2) Fallback PyMuPDF (sin dependencia de poppler).
        """
        try:
            images = await asyncio.to_thread(
                convert_from_path,
                file_path,
                dpi=120,
                first_page=page_num,
                last_page=page_num,
                fmt="jpeg",
            )
            if images:
                img = images[0]
                buffered = BytesIO()
                img.save(buffered, format="JPEG")
                data = base64.b64encode(buffered.getvalue()).decode("utf-8")
                del images
                del img
                gc.collect()
                return data
        except Exception as exc:
            logger.warning(
                "[%s] convert_from_path falló en página %s; fallback PyMuPDF. error=%s",
                self.name,
                page_num,
                str(exc),
            )

        try:
            # Fallback robusto para entornos host sin poppler.
            with fitz.open(file_path) as doc:
                page = doc.load_page(page_num - 1)
                pix = page.get_pixmap(dpi=150, alpha=False)
                data = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
                return data
        except Exception as exc:
            logger.error(
                "[%s] Fallback PyMuPDF falló en página %s: %s",
                self.name,
                page_num,
                str(exc),
            )
            return None

    async def extract_page_vision(self, file_path: str, page_num: int) -> str:
        """Realiza la extracción visual de una página individual (VLM-OCR)."""
        try:
            img_str = await self._render_page_base64(file_path, page_num)
            if not img_str:
                return ""

            payload = {
                "model": "glm-ocr",
                "prompt": (
                    "ANALIZAR Y TRANSCRIBIR DE FORMA FORENSE ESTA PÁGINA DE LICITACIÓN.\n"
                    "INSTRUCCIONES DE ALTA FIDELIDAD:\n"
                    "1. Extrae TODO el texto con precisión quirúrgica, palabra por palabra.\n"
                    "2. Transcribe estrictamente todos los números, porcentajes (ej. 80%, 90%, 2%), constantes, fórmulas, fechas y valores monetarios. PROHIBIDO resumir o generalizar.\n"
                    "3. Si hay tablas o anexos, formatéalos como tablas de Markdown estrictas (| Celda 1 | Celda 2 |). Asegura un orden de lectura lineal perfecto de izquierda a derecha y de arriba a abajo.\n"
                    "4. No agregues introducciones, comentarios ni explicaciones. Devuelve únicamente la transcripción del texto de la imagen."
                ),
                "images": [img_str],
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_ctx": 16384,
                    "num_predict": 4096
                }
            }

            request_url = f"{self.ollama_url.strip('/')}/api/generate"
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with OllamaGuard("VLM (glm-ocr)", VLM_SEMAPHORE):
                    print(f"[{self.name}] Procesando Pag {page_num} con GLM-OCR (Página Individual)...")
                    res = await client.post(request_url, json=payload)
                    res.raise_for_status()
                    result_data = res.json()
                    
                    if result_data:
                        text = (result_data.get("response", "") or "").strip()
                        # Limpiar bloques markdown si existen
                        text = text.replace("```markdown", "").replace("```text", "").replace("```", "").strip()
                        return text
            return ""
        except Exception as e:
            logger.error(f"[{self.name}] Error en extraccion visual de pagina {page_num}: {e}")
            return ""

    async def extract(self, file_path: str) -> Dict[str, Any]:
        """
        Realiza la extracción visual de un PDF (OCR).
        
        Args:
            file_path: Ruta absoluta al archivo PDF.
            
        Returns:
            Dict con el texto reconstruido, lista de páginas, estadísticas y éxito.
        """
        print(f"[{self.name}] Iniciando extraccion visual (VLM-OCR): {file_path}")
        
        if not os.path.exists(file_path):
            logger.error(f"[{self.name}] Archivo no encontrado: {file_path}")
            return {"error": "Archivo no encontrado", "success": False}
            
        try:
            total_pages = self._get_total_pages_with_fallback(file_path)

            # --- ESTRATEGIA DE PROCESAMIENTO POR PÁGINAS ---
            MAX_PAGES = int(os.getenv("VISION_MAX_PAGES", "0"))
            process_limit = total_pages if MAX_PAGES <= 0 else min(total_pages, MAX_PAGES)
            
            print(f"[{self.name}] Procesando {process_limit} de {total_pages} paginas...")

            full_text = ""
            extracted_pages = []
            total_chars = 0
            
            async with httpx.AsyncClient(timeout=600.0) as client:
                for start in range(1, process_limit + 1):
                    text = ""
                    try:
                        img_str = await self._render_page_base64(file_path, start)
                        if not img_str:
                            continue

                        payload = {
                            "model": "glm-ocr",
                            "prompt": (
                                "Extract all text from this page accurately. "
                                "If you detect tables, format them strictly as Markdown tables (| Col | Col |). "
                                "Do not skip any numeric data or dates."
                            ),
                            "images": [img_str],
                            "stream": False,
                            "options": {
                                "temperature": 0.0,
                                "num_ctx": 16384,
                                "num_predict": 4096
                            }
                        }

                        request_url = f"{self.ollama_url.strip('/')}/api/generate"
                        
                        async with OllamaGuard("VLM (glm-ocr)", VLM_SEMAPHORE):
                            print(f"[{self.name}] Procesando Pag {start} con GLM-OCR...")
                            res = await client.post(request_url, json=payload)
                            res.raise_for_status()
                            result_data = res.json()
                            
                            if result_data:
                                text = (result_data.get("response", "") or "").strip()
                                # Limpiar bloques markdown si existen
                                text = text.replace("```markdown", "").replace("```text", "").replace("```", "").strip()

                        if not text:
                            logger.warning(f"[{self.name}] Pagina {start} devolvio texto vacio.")

                        extracted_pages.append({"page": start, "text": text})
                        full_text += f"\n--- PÁGINA {start} ---\n{text}\n"
                        total_chars += len(text)
                        
                        del img_str
                        gc.collect()

                    except Exception as e:
                        logger.error(f"[{self.name}] Error en pagina {start}: {e}")
                        continue
                        
            MIN_CHARS = int(os.getenv("VISION_MIN_CHARS", "100"))
            success = total_chars >= MIN_CHARS
            
            return {
                "extracted_text": full_text.strip(),
                "pages": extracted_pages,
                "total_pages": len(extracted_pages),
                "success": success,
                "method": "vlm_ocr_vision",
                "stats": {"chars": total_chars, "pages_ok": len(extracted_pages)}
            }

        except Exception as exc:
            logger.error(f"[{self.name}] Error critico en extraccion visual: {exc}")
            return {"error": str(exc), "success": False}
