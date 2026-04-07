import httpx
import os
import json
from typing import Dict, Any, List, Optional
from app.utils.gpu_lock import LLM_SEMAPHORE

class LLMServiceClient:
    """Cliente HTTP para interactuar con la API REST de Ollama"""
    
    def __init__(self):
        self.base_url = os.getenv("LLM_URL", "http://llm-inference:11434")
        self.timeout = 600.0 # Aumentado a 10 minutos para procesar contextos pesados (>30k chars)
        self.default_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None, images: Optional[List[str]] = None, format: Optional[str] = None) -> Dict[str, Any]:
        """Genera una respuesta basada en un prompt y opcionalmente imágenes (Base64)."""
        url = f"{self.base_url}/api/generate"
        # num_predict: tope de tokens de SALIDA; sin esto Ollama suele truncar JSON grandes (p. ej. listas a…bb en compliance).
        _np_raw = os.getenv("OLLAMA_NUM_PREDICT", "4096").strip()
        try:
            _num_predict = int(_np_raw) if _np_raw else 4096
        except ValueError:
            _num_predict = 4096
        _num_predict = max(256, min(_num_predict, 131072))

        payload = {
            "model": model or self.default_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,  # Temperatura 0.0 para CERO alucinación / máxima exactitud.
                "num_ctx": 16384,  # Ventana de contexto para bases largas
                "num_predict": _num_predict,
            },
        }
        if system_prompt:
             payload["system"] = system_prompt
        if images:
             payload["images"] = images # Lista de strings en Base64
        if format:
             payload["format"] = format
             
        try:
            # ─── VRAM GUARD: Solo 1 llamada LLM activa a la vez ────────────────────
            async with LLM_SEMAPHORE:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            return {"response": data.get("response", ""), "context": data.get("context", [])}
        except Exception as exc:
            return {"error": str(exc)}

    async def chat(self, messages: List[Dict[str, str]], model: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Genera respuesta manteniendo el historial (RolePlay). messages debe ser [{'role': 'user', 'content': 'hola'}]"""
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
            "options": options or {"temperature": 0.3} # Temperatura baja por defecto para licitaciones precisas
        }
        
        try:
            # ─── VRAM GUARD: Solo 1 llamada LLM activa a la vez ────────────────────
            async with LLM_SEMAPHORE:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            return {"message": data.get("message", {"content": ""})}
        except Exception as exc:
            return {"error": str(exc)}

    async def health_check(self) -> bool:
        url = f"{self.base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                return res.status_code == 200
        except Exception:
            return False
