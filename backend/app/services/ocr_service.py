import httpx
import os
import asyncio
import fitz
from typing import Dict, Any, Optional
from app.agents.extractor_digital import DigitalExtractorAgent
from app.agents.extractor_vision import VisionExtractorAgent
from app.utils.ocr_quality import looks_like_low_signal_ocr


def _normalize_extraction_result(result: Dict[str, Any], default_method: str) -> Dict[str, Any]:
    """Normaliza la salida OCR a un contrato canónico mínimo."""
    pages = result.get("pages", []) or []
    extracted_text = (result.get("extracted_text") or "").strip()
    if not extracted_text and pages:
        extracted_text = "\n".join((p.get("text") or "").strip() for p in pages if (p.get("text") or "").strip())
    chars_total = len(extracted_text)
    pages_with_text = sum(1 for p in pages if (p.get("text") or "").strip())
    normalized = dict(result)
    normalized["success"] = bool(result.get("success", False))
    normalized["method"] = result.get("method", default_method)
    normalized["pages"] = pages
    normalized["total_pages"] = result.get("total_pages", len(pages))
    normalized["extracted_text"] = extracted_text
    normalized["stats"] = {
        "chars_total": chars_total,
        "pages_with_text": pages_with_text,
    }
    normalized.setdefault("quality_flags", [])
    normalized.setdefault("error_type", None)
    normalized.setdefault("error_message", result.get("error"))
    return normalized

class OCRServiceClient:
    """
    Entrada canónica para texto desde PDF/imagen en la app.

    Jerarquía: DigitalExtractor (nativo) -> ocr-vlm remoto (si hay health) -> VisionExtractor.

    Consumidores:
    - Camino A (explícito): ``POST .../upload/process/{doc_id}`` — el usuario fuerza extracción/indexación del doc.
    - Camino B (background): auto-ingesta en ``agents._run_orchestrator_job`` antes del orquestador.
    - Empresas: ``companies.analyze_company`` para docs con status UPLOADED.

    Excel/CSV no pasan por aquí; usan ingestores tabulares dedicados.
    """
    
    def __init__(self):
        self.base_url = os.getenv("OCR_URL", "http://ocr-vlm:8082")
        self.timeout = 900.0
        self.digital_extractor = DigitalExtractorAgent()
        self.vision_extractor = VisionExtractorAgent()

    async def scan_document(self, file_path: str) -> Dict[str, Any]:
        """Extrae texto del documento usando una estrategia híbrida página por página (Hito 12)."""
        print(f"[*] [OCR] Iniciando extracción híbrida página por página: {file_path}")

        if not os.path.exists(file_path):
            return {
                "error": "Archivo no encontrado",
                "success": False,
                "pages": [],
                "extracted_text": "",
            }

        try:
            doc = fitz.open(file_path)
            total_pages = len(doc)
            print(f"[*] [OCR] PDF abierto con éxito. Total páginas: {total_pages}")
            
            pages_extracted = []
            full_text_parts = []
            
            for i, page in enumerate(doc):
                page_num = i + 1
                # 1. Intentar extracción digital para esta página
                page_text_digital = self.digital_extractor.extract_page_digital(page)
                
                # 2. Evaluar señal digital de la página
                # Exigimos al menos 50 caracteres significativos y que no parezca solo ruido de paginación/números sueltos
                is_high_signal = len(page_text_digital.strip()) > 50 and not looks_like_low_signal_ocr(page_text_digital)
                
                if is_high_signal:
                    print(f"[*] [OCR] Página {page_num}/{total_pages} -> EXTRAÍDA DIGITALMENTE (Señal Alta).")
                    pages_extracted.append({
                        "page": page_num,
                        "text": page_text_digital,
                        "method": "pymupdf_digital"
                    })
                    full_text_parts.append(f"\n--- PÁGINA {page_num} ---\n{page_text_digital}\n")
                else:
                    # 3. Fallback a Visión (VLM-OCR) para esta página específica
                    print(f"[*] [OCR] Página {page_num}/{total_pages} -> BAJA SEÑAL O ESCANEADA. Iniciando VLM-OCR...")
                    
                    page_text_vision = ""
                    # Intentar Microservicio Remoto ocr-vlm si está disponible
                    if await self.health_check():
                        try:
                            async with httpx.AsyncClient(timeout=60.0) as client:
                                # Usar endpoint de extracción de página única si existe
                                resp = await client.post(
                                    f"{self.base_url}/api/v1/extract_page", 
                                    data={"file_path": file_path, "page_num": page_num}, 
                                    timeout=60.0
                                )
                                if resp.status_code == 200:
                                    page_text_vision = resp.json().get("text", "")
                        except Exception as remote_err:
                            print(f"⚠️ [OCR] Fallo al extraer página {page_num} vía microservicio remoto: {remote_err}")
                    
                    # Si no se pudo obtener de forma remota, usar el extractor de visión nativo
                    if not page_text_vision.strip():
                        page_text_vision = await self.vision_extractor.extract_page_vision(file_path, page_num)
                        
                    if page_text_vision.strip():
                        print(f"[*] [OCR] Página {page_num}/{total_pages} -> EXTRAÍDA VÍA VLM-OCR con éxito.")
                        pages_extracted.append({
                            "page": page_num,
                            "text": page_text_vision,
                            "method": "vlm_ocr_vision"
                        })
                        full_text_parts.append(f"\n--- PÁGINA {page_num} ---\n{page_text_vision}\n")
                    else:
                        # Respaldo final si todo falla
                        print(f"⚠️ [OCR] Página {page_num}/{total_pages} -> Falló extracción visual. Usando texto digital básico.")
                        pages_extracted.append({
                            "page": page_num,
                            "text": page_text_digital,
                            "method": "pymupdf_digital_fallback"
                        })
                        full_text_parts.append(f"\n--- PÁGINA {page_num} ---\n{page_text_digital}\n")

            full_text = "".join(full_text_parts).strip()
            total_chars = len(full_text)
            print(f"[*] [OCR] Extracción híbrida finalizada. Total caracteres extraídos: {total_chars}")
            
            return {
                "success": total_chars > 100,
                "method": "hybrid_page_by_page",
                "pages": pages_extracted,
                "total_pages": total_pages,
                "extracted_text": full_text,
                "stats": {
                    "chars_total": total_chars,
                    "pages_with_text": len([p for p in pages_extracted if p["text"].strip()]),
                },
                "quality_flags": [],
                "error_type": None,
                "error_message": None
            }
            
        except Exception as e:
            print(f"❌ [OCR] Error crítico en extracción híbrida: {e}")
            return _normalize_extraction_result(
                {
                    "error": f"Fallo total en extracción híbrida: {str(e)}",
                    "error_type": "HYBRID_EXCEPTION",
                    "success": False,
                    "pages": [],
                    "extracted_text": "",
                },
                "hybrid_page_by_page_failed",
            )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except:
            return False
