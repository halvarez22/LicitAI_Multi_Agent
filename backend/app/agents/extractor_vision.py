from app.core.logging_config import get_logger
import httpx
import os
import gc
import asyncio
import base64
from io import BytesIO
from typing import Any, Dict, List, Optional
from pdf2image import pdfinfo_from_path, convert_from_path
import fitz  # PyMuPDF

logger = get_logger(__name__)

from app.utils.gpu_lock import VLM_SEMAPHORE, OllamaGuard
from app.utils.ocr_quality import assess_vlm_page_quality, is_usable_vlm_page_text

# Prompt alineado al uso nativo de glm-ocr en Ollama (evita eco de instrucciones largas).
GLM_OCR_MODEL = os.getenv("GLM_OCR_MODEL", "glm-ocr")
GLM_OCR_PROMPT_PRIMARY = (
    "Text Recognition:\nExtract all text from this image accurately."
)
GLM_OCR_PROMPT_RETRY = (
    "Text Recognition:\n"
    "Transcribe every word, number, date and table cell from this document page. "
    "Format tables as Markdown. Output only the transcribed text, no instructions."
)


class VisionExtractorAgent:
    """
    Agente especialista en OCR avanzado vía VLM (Vision-Language Model).
    Utiliza GLM-OCR para extraer texto de documentos escaneados o imágenes.
    Requiere aceleración por GPU y gestiona el acceso mediante semáforos.
    """

    def __init__(self, ollama_url: Optional[str] = None):
        self.name = "VisionExtractorAgent"
        self.ollama_url = ollama_url or os.getenv(
            "LLM_URL", os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
        )

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

    @staticmethod
    def _clean_vlm_response(text: str) -> str:
        s = (text or "").strip()
        for token in ("```markdown", "```text", "```"):
            s = s.replace(token, "")
        return s.strip()

    async def _invoke_glm_ocr(
        self,
        client: httpx.AsyncClient,
        img_str: str,
        prompt: str,
        page_num: int,
    ) -> str:
        payload = {
            "model": GLM_OCR_MODEL,
            "prompt": prompt,
            "images": [img_str],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_ctx": 16384,
                "num_predict": 4096,
            },
        }
        request_url = f"{self.ollama_url.strip('/')}/api/generate"
        async with OllamaGuard("VLM (glm-ocr)", VLM_SEMAPHORE):
            print(f"[{self.name}] Procesando Pag {page_num} con GLM-OCR...")
            res = await client.post(request_url, json=payload)
            res.raise_for_status()
            result_data = res.json()
            if result_data:
                return self._clean_vlm_response(result_data.get("response", "") or "")
        return ""

    async def extract_page_vision_detail(
        self, file_path: str, page_num: int
    ) -> Dict[str, Any]:
        """
        Extracción VLM de una página con reintento y flags de calidad.

        Returns:
            Dict con ``text``, ``method``, ``quality_flags``, ``prompt_variant``.
        """
        empty: Dict[str, Any] = {
            "text": "",
            "method": "vlm_ocr_vision",
            "quality_flags": ["empty"],
            "prompt_variant": "none",
        }
        try:
            img_str = await self._render_page_base64(file_path, page_num)
            if not img_str:
                return empty

            min_chars = int(os.getenv("VISION_MIN_CHARS_PAGE", "80"))
            async with httpx.AsyncClient(timeout=300.0) as client:
                primary = await self._invoke_glm_ocr(
                    client, img_str, GLM_OCR_PROMPT_PRIMARY, page_num
                )
                if is_usable_vlm_page_text(primary, min_chars=min_chars):
                    return {
                        "text": primary,
                        "method": "vlm_ocr_vision",
                        "quality_flags": assess_vlm_page_quality(primary, min_chars=min_chars),
                        "prompt_variant": "primary",
                    }

                retry = await self._invoke_glm_ocr(
                    client, img_str, GLM_OCR_PROMPT_RETRY, page_num
                )
                if is_usable_vlm_page_text(retry, min_chars=min_chars):
                    return {
                        "text": retry,
                        "method": "vlm_ocr_vision_retry",
                        "quality_flags": assess_vlm_page_quality(retry, min_chars=min_chars),
                        "prompt_variant": "retry",
                    }

                best = retry if len(retry) > len(primary) else primary
                flags = assess_vlm_page_quality(best, min_chars=min_chars)
                if not flags:
                    flags = ["vlm_low_quality"]
                return {
                    "text": best,
                    "method": "vlm_ocr_vision_retry" if retry else "vlm_ocr_vision",
                    "quality_flags": flags,
                    "prompt_variant": "retry" if retry else "primary",
                }
        except Exception as exc:
            logger.error(
                "[%s] Error en extraccion visual de pagina %s: %s",
                self.name,
                page_num,
                exc,
            )
            return {**empty, "quality_flags": ["error"]}

    async def extract_page_vision(self, file_path: str, page_num: int) -> str:
        """Realiza la extracción visual de una página individual (VLM-OCR)."""
        detail = await self.extract_page_vision_detail(file_path, page_num)
        return str(detail.get("text") or "")

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
            MAX_PAGES = int(os.getenv("VISION_MAX_PAGES", "0"))
            process_limit = total_pages if MAX_PAGES <= 0 else min(total_pages, MAX_PAGES)

            print(f"[{self.name}] Procesando {process_limit} de {total_pages} paginas...")

            full_text = ""
            extracted_pages: List[Dict[str, Any]] = []
            total_chars = 0
            bad_pages = 0

            for start in range(1, process_limit + 1):
                try:
                    detail = await self.extract_page_vision_detail(file_path, start)
                    text = str(detail.get("text") or "")
                    flags = list(detail.get("quality_flags") or [])
                    if flags and flags != ["empty"]:
                        bad_pages += 1

                    extracted_pages.append(
                        {
                            "page": start,
                            "text": text,
                            "method": detail.get("method", "vlm_ocr_vision"),
                            "quality_flags": flags,
                        }
                    )
                    full_text += f"\n--- PÁGINA {start} ---\n{text}\n"
                    total_chars += len(text)
                    gc.collect()
                except Exception as exc:
                    logger.error(f"[{self.name}] Error en pagina {start}: {exc}")
                    continue

            MIN_CHARS = int(os.getenv("VISION_MIN_CHARS", "100"))
            success = total_chars >= MIN_CHARS

            return {
                "extracted_text": full_text.strip(),
                "pages": extracted_pages,
                "total_pages": len(extracted_pages),
                "success": success,
                "method": "vlm_ocr_vision",
                "stats": {
                    "chars": total_chars,
                    "pages_ok": len(extracted_pages),
                    "pages_with_quality_flags": bad_pages,
                },
            }

        except Exception as exc:
            logger.error(f"[{self.name}] Error critico en extraccion visual: {exc}")
            return {"error": str(exc), "success": False}
