"""
GPU / VRAM Lock Module
======================
Control de acceso global a Ollama (VLM + LLM) para serializar todas las
llamadas que consumen VRAM. Con solo 8 GB en la RTX 4060, correr dos modelos
simultáneamente garantiza un CUDA OOM. Este módulo es el único guardián.

REGLA DE ORO: Todo agente que hable con Ollama DEBE hacerlo dentro de:
    async with VLM_SEMAPHORE:   # para modelos de visión (qwen3-vl, etc.)
    async with LLM_SEMAPHORE:   # para modelos de texto (llama3.1, etc.)
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# ─── Semáforo para modelos de VISIÓN (~4-6 GB VRAM) ─────────────────────────
# Permite 0 llamadas concurrentes a VLM. Solo 1 a la vez.
VLM_SEMAPHORE = asyncio.Semaphore(1)

# ─── Semáforo para modelos de TEXTO (~5.5 GB VRAM llama3.1:8b) ───────────────
# También 1 a la vez: el LLM y el VLM no pueden coexistir en 8 GB.
LLM_SEMAPHORE = asyncio.Semaphore(1)

# ─── Lock maestro: evita que VLM+LLM corran al mismo tiempo ─────────────────
# Si se usa este lock, NINGÚN modelo de Ollama corre mientras otro está activo.
OLLAMA_MASTER_LOCK = asyncio.Lock()


class OllamaGuard:
    """
    Context manager decorador para uso explícito con logging.

    Uso:
        async with OllamaGuard("VLM", VLM_SEMAPHORE):
            # llamada a Ollama VLM aquí
    """

    def __init__(self, model_type: str, semaphore: asyncio.Semaphore):
        self.model_type = model_type
        self.semaphore = semaphore

    async def __aenter__(self):
        logger.info(f"[GPU_LOCK] ⏳ Esperando slot para {self.model_type}...")
        await self.semaphore.acquire()
        logger.info(f"[GPU_LOCK] ✅ Slot VRAM adquirido para {self.model_type}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.semaphore.release()
        logger.info(f"[GPU_LOCK] 🔓 Slot VRAM liberado de {self.model_type}")
        return False  # No suprimir excepciones
