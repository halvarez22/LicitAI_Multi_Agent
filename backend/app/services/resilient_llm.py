"""
resilient_llm.py — Fase 0 Hardening
Wrapper resiliente sobre LLMServiceClient con:
  - Timeout tipado
  - Retry con backoff exponencial
  - Circuit Breaker (open/half-open/closed)
  - Fallback opcional a modelo secundario
  - Retorno de estructura controlada (nunca excepción cruda al caller)

Feature flags (env vars):
  LLM_RETRY_MAX_ATTEMPTS   (default 3)
  LLM_RETRY_BASE_DELAY_SEC (default 1.0)
  LLM_CB_FAILURE_THRESHOLD (default 5)
  LLM_CB_RECOVERY_TIMEOUT  (default 30)
  LLM_FALLBACK_MODEL       (default "")  — vacío = sin fallback
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.services.llm_service import LLMServiceClient

logger = logging.getLogger(__name__)


# ─── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"        # Normal — permite llamadas
    OPEN = "open"            # Bloqueado — rechaza llamadas directo
    HALF_OPEN = "half_open"  # Probando recuperación


@dataclass
class CircuitBreaker:
    """
    Circuit Breaker básico (no distribuido — en memoria por proceso).
    Para el caso de LicitAI con Ollama local es suficiente: un solo proceso.
    """
    failure_threshold: int = 5
    recovery_timeout_sec: float = 30.0

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _correlation_id: str = field(default="", init=False)

    @property
    def state(self) -> CircuitState:
        # Transición automática OPEN → HALF_OPEN tras recovery_timeout
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout_sec
        ):
            logger.info(
                "[CircuitBreaker] OPEN→HALF_OPEN (recovery_timeout=%.1fs expirado)",
                self.recovery_timeout_sec,
            )
            self._state = CircuitState.HALF_OPEN
        return self._state

    def record_success(self) -> None:
        if self._state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            logger.info("[CircuitBreaker] Recuperación exitosa → CLOSED")
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def record_failure(self, correlation_id: str = "") -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        self._correlation_id = correlation_id

        if self._state == CircuitState.HALF_OPEN:
            logger.warning(
                "[CircuitBreaker] HALF_OPEN→OPEN (falló en prueba) correlation_id=%s",
                correlation_id,
            )
            self._state = CircuitState.OPEN
        elif self._failure_count >= self.failure_threshold:
            logger.error(
                "[CircuitBreaker] CLOSED→OPEN (umbral=%d alcanzado) correlation_id=%s",
                self.failure_threshold,
                correlation_id,
            )
            self._state = CircuitState.OPEN

    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN


# Instancia singleton por proceso
_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker(
            failure_threshold=int(os.getenv("LLM_CB_FAILURE_THRESHOLD", "5")),
            recovery_timeout_sec=float(os.getenv("LLM_CB_RECOVERY_TIMEOUT", "30")),
        )
    return _circuit_breaker


def reset_circuit_breaker() -> None:
    """Para uso en tests solamente."""
    global _circuit_breaker
    _circuit_breaker = None


# ─── LLM Response wrapper ────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """
    Respuesta controlada del wrapper LLM.
    El caller NUNCA recibe una excepción cruda — siempre un LLMResponse.
    """
    success: bool
    response: str = ""
    context: List[Any] = field(default_factory=list)
    error: Optional[str] = None
    attempts: int = 1
    used_fallback: bool = False
    circuit_state: str = CircuitState.CLOSED

    def to_legacy_dict(self) -> Dict[str, Any]:
        """Compatibilidad con código que espera {'response': '...', 'error': '...'}."""
        if self.success:
            return {"response": self.response, "context": self.context}
        return {"error": self.error or "LLM unavailable", "response": ""}


# ─── Resilient LLM Client ────────────────────────────────────────────────────

class ResilientLLMClient:
    """
    Wrapper resiliente sobre LLMServiceClient.
    Remplaza el uso directo de self.llm.generate() en los agentes.

    Uso (backward compatible):
        llm = ResilientLLMClient()
        result = await llm.generate(prompt=..., correlation_id=session_id)
        # result.to_legacy_dict() para código heredado
    """

    def __init__(self) -> None:
        self._base = LLMServiceClient()
        self._cb = get_circuit_breaker()
        self._max_attempts = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS", "3"))
        self._base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_SEC", "1.0"))
        self._fallback_model = os.getenv("LLM_FALLBACK_MODEL", "").strip() or None

    @property
    def service_client(self) -> LLMServiceClient:
        """Cliente HTTP base (sin reintentos de red). Para flujos con reintento propio p. ej. map JSON compliance."""
        return self._base

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        images: Optional[List[str]] = None,
        format: Optional[str] = None,
        correlation_id: str = "",
    ) -> LLMResponse:
        """
        Genera respuesta con resiliencia completa.
        Nunca lanza excepción — siempre retorna LLMResponse.
        """
        # ── Circuit Breaker: rechazar si está OPEN ──────────────────────────
        if self._cb.is_open():
            logger.error(
                "[ResilientLLM] Circuit OPEN — rechazando llamada correlation_id=%s",
                correlation_id,
            )
            return LLMResponse(
                success=False,
                error="LLM circuit breaker OPEN — servicio temporalmente no disponible",
                attempts=0,
                circuit_state=self._cb.state,
            )

        # ── Retry con backoff exponencial ───────────────────────────────────
        last_error: str = ""
        for attempt in range(1, self._max_attempts + 1):
            try:
                logger.debug(
                    "[ResilientLLM] Intento %d/%d correlation_id=%s",
                    attempt, self._max_attempts, correlation_id,
                )
                raw = await self._base.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model,
                    images=images,
                    format=format,
                )

                if "error" in raw:
                    raise RuntimeError(str(raw["error"]))

                self._cb.record_success()
                logger.info(
                    "[ResilientLLM] OK intento=%d correlation_id=%s chars=%d",
                    attempt, correlation_id, len(raw.get("response", "")),
                )
                return LLMResponse(
                    success=True,
                    response=raw.get("response", ""),
                    context=raw.get("context", []),
                    attempts=attempt,
                    circuit_state=self._cb.state,
                )

            except Exception as exc:
                last_error = str(exc)
                self._cb.record_failure(correlation_id)
                logger.warning(
                    "[ResilientLLM] Fallo intento=%d/%d error=%s correlation_id=%s",
                    attempt, self._max_attempts, last_error[:200], correlation_id,
                )

                if self._cb.is_open():
                    logger.error(
                        "[ResilientLLM] Circuit abierto tras fallo — abortando reintentos correlation_id=%s",
                        correlation_id,
                    )
                    break

                if attempt < self._max_attempts:
                    delay = self._base_delay * (2 ** (attempt - 1))
                    logger.info(
                        "[ResilientLLM] Backoff %.1fs antes de intento %d correlation_id=%s",
                        delay, attempt + 1, correlation_id,
                    )
                    await asyncio.sleep(delay)

        # ── Fallback a modelo secundario (si configurado) ───────────────────
        if self._fallback_model:
            logger.warning(
                "[ResilientLLM] Intentando fallback model=%s correlation_id=%s",
                self._fallback_model, correlation_id,
            )
            try:
                raw = await self._base.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=self._fallback_model,
                    images=images,
                    format=format,
                )
                if "error" not in raw:
                    self._cb.record_success()
                    return LLMResponse(
                        success=True,
                        response=raw.get("response", ""),
                        context=raw.get("context", []),
                        attempts=self._max_attempts + 1,
                        used_fallback=True,
                        circuit_state=self._cb.state,
                    )
            except Exception as exc:
                logger.error(
                    "[ResilientLLM] Fallback también falló: %s correlation_id=%s",
                    str(exc)[:200], correlation_id,
                )

        return LLMResponse(
            success=False,
            error=f"LLM no disponible tras {self._max_attempts} intentos: {last_error}",
            attempts=self._max_attempts,
            circuit_state=self._cb.state,
        )

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        correlation_id: str = "",
    ) -> LLMResponse:
        """
        Chat resiliente (mismo patrón que generate).
        """
        if self._cb.is_open():
            return LLMResponse(
                success=False,
                error="LLM circuit breaker OPEN",
                attempts=0,
                circuit_state=self._cb.state,
            )

        last_error = ""
        for attempt in range(1, self._max_attempts + 1):
            try:
                raw = await self._base.chat(messages=messages, model=model, options=options)
                if "error" in raw:
                    raise RuntimeError(str(raw["error"]))
                self._cb.record_success()
                content = raw.get("message", {}).get("content", "")
                return LLMResponse(
                    success=True,
                    response=content,
                    attempts=attempt,
                    circuit_state=self._cb.state,
                )
            except Exception as exc:
                last_error = str(exc)
                self._cb.record_failure(correlation_id)
                if self._cb.is_open():
                    break
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._base_delay * (2 ** (attempt - 1)))

        return LLMResponse(
            success=False,
            error=f"Chat LLM no disponible: {last_error}",
            attempts=self._max_attempts,
            circuit_state=self._cb.state,
        )
