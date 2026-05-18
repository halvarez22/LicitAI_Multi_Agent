import httpx
import os
import asyncio
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
        """Extrae texto del documento usando el mejor motor disponible."""
        print(f"[*] [OCR] Iniciando extracción: {file_path}")

        # --- PASO 0: EXTRACCIÓN DIGITAL (vía agente dedicado) ---
        digital_res = await self.digital_extractor.extract(file_path)
        if digital_res.get("success"):
            digital_norm = _normalize_extraction_result(digital_res, "pymupdf_digital")
            # Si el texto digital es ruido (paginación/números), forzar fallback visual.
            if not looks_like_low_signal_ocr(digital_norm.get("extracted_text", "")):
                return digital_norm
            print("[*] [OCR] Texto digital de baja señal; activando fallback visual.")

        # --- PASO 1: FALLBACK A VISIÓN (Jerarquía) ---
        # 🧪 INTENTO 1: Microservicio Remoto (Docker ocr-vlm)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                health_res = await client.get(f"{self.base_url}/health")
                if health_res.status_code == 200:
                    print("[*] [OCR] Usando motor remoto ocr-vlm...")
                    # Lógica de polling (simplificada para robustez)
                    resp = await client.post(f"{self.base_url}/api/v1/extract", data={"file_path": file_path}, timeout=300.0)
                    if resp.status_code == 200:
                        task_id = resp.json().get("task_id")
                        for _ in range(150): # 5 mins
                            status_res = await client.get(f"{self.base_url}/api/v1/status/{task_id}")
                            st_data = status_res.json()
                            if st_data.get("status") == "completed":
                                res = st_data.get("result", {})
                                res["method"] = "vlm_ocr_remote"
                                return _normalize_extraction_result(res, "vlm_ocr_remote")
                            await asyncio.sleep(2.0)
        except Exception as e:
            print(f"⚠️ [OCR] Motor remoto no disponible ({e}).")

        # 🧪 INTENTO 2: Agente Nativo (Ollama + glm-ocr) -> LA GARANTÍA FINAL
        print("[*] [OCR] Activando Agente de Visión Nativo...")
        try:
            res_native = await self.vision_extractor.extract(file_path)
            if res_native.get("success"):
                res_native["method"] = "vlm_ocr_native_fallback"
                return _normalize_extraction_result(res_native, "vlm_ocr_native_fallback")
            failed = _normalize_extraction_result(res_native, "vlm_ocr_native_fallback")
            failed["error_type"] = failed.get("error_type") or "OCR_FAILED"
            return failed
        except Exception as e:
            return _normalize_extraction_result(
                {
                    "error": f"Fallo total en cadena de OCR: {str(e)}",
                    "error_type": "OCR_EXCEPTION",
                    "success": False,
                    "pages": [],
                    "extracted_text": "",
                },
                "vlm_ocr_native_fallback",
            )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except:
            return False
