import httpx
import os, logging
import gc
import asyncio
import base64
from io import BytesIO
from typing import Dict, Any, Optional
from pdf2image import pdfinfo_from_path, convert_from_path

logger = logging.getLogger(__name__)

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
            info = pdfinfo_from_path(file_path)
            total_pages = int(info['Pages'])

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
                        images = await asyncio.to_thread(
                            convert_from_path, 
                            file_path, 
                            dpi=120,
                            first_page=start, 
                            last_page=start, 
                            fmt="jpeg"
                        )
                        
                        if not images: continue
                        img = images[0]
                        buffered = BytesIO()
                        img.save(buffered, format="JPEG")
                        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                        del images
                        del img
                        gc.collect()

                        payload = {
                            "model": "glm-ocr",
                            "prompt": "Text Recognition: ",
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
