import httpx
import os
import asyncio
import traceback
from typing import Dict, Any, Optional

class OCRServiceClient:
    """Cliente de OCR con Jerarquía de Resiliencia: Digital -> Remoto -> Nativo."""
    
    def __init__(self):
        self.base_url = os.getenv("OCR_URL", "http://ocr-vlm:8082")
        self.timeout = 900.0

    async def scan_document(self, file_path: str) -> Dict[str, Any]:
        """Extrae texto del documento usando el mejor motor disponible."""
        print(f"[*] [OCR] Iniciando extracción: {file_path}")
        
        # --- PASO 0: EXTRACCIÓN DIGITAL (PyMuPDF) ---
        try:
            import fitz
            if os.path.exists(file_path) and file_path.lower().endswith(".pdf"):
                doc = fitz.open(file_path)
                full_text = ""
                extracted_pages = []
                for i, page in enumerate(doc):
                    text = page.get_text().strip()
                    extracted_pages.append({"page": i+1, "text": text})
                    full_text += f"\n--- PÁGINA {i+1} ---\n{text}\n"
                
                if len(full_text.strip()) > 100:
                    print(f"✅ [OCR] Éxito Digital ({len(full_text)} chars).")
                    return {
                        "total_pages": len(doc),
                        "extracted_text": full_text.strip(),
                        "pages": extracted_pages,
                        "method": "pymupdf_digital",
                        "success": True # CRÍTICO para el contrato de éxito
                    }
        except Exception as e:
            print(f"[⚠️] Error en extracción digital: {e}")

        # --- PASO 1: FALLBACK A VISIÓN (Jerarquía) ---
        from app.agents.extractor_vision import VisionExtractorAgent
        agent_vision = VisionExtractorAgent()

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
                                return res
                            await asyncio.sleep(2.0)
        except Exception as e:
            print(f"⚠️ [OCR] Motor remoto no disponible ({e}).")

        # 🧪 INTENTO 2: Agente Nativo (Ollama + glm-ocr) -> LA GARANTÍA FINAL
        print("[*] [OCR] Activando Agente de Visión Nativo...")
        try:
            res_native = await agent_vision.extract(file_path)
            if res_native.get("success"):
                res_native["method"] = "vlm_ocr_native_fallback"
                return res_native
            return res_native
        except Exception as e:
            return {"error": f"Fallo total en cadena de OCR: {str(e)}", "success": False}

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except:
            return False
