"""
test_fase0_resilient_llm.py
Tests unitarios para el wrapper LLM resiliente de Fase 0.
Valida: retry/backoff, circuit breaker, fallback.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.resilient_llm import (
    CircuitBreaker,
    CircuitState,
    ResilientLLMClient,
    LLMResponse,
    reset_circuit_breaker,
)


@pytest.fixture(autouse=True)
def reset_cb():
    """Reset circuit breaker singleton between tests."""
    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


# ─── CircuitBreaker ──────────────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout_sec=30)
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open()

    def test_n_failures_opens_breaker(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure("test-id")
        assert cb.state == CircuitState.OPEN
        assert cb.is_open()

    def test_fewer_than_threshold_stays_closed(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure("test-id")
        assert cb.state == CircuitState.CLOSED

    def test_success_after_open_closes_via_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout_sec=0.01)
        cb.record_failure("t")
        cb.record_failure("t")
        assert cb.is_open()

        # Esperar recovery timeout
        import time
        time.sleep(0.05)

        # Ahora debe estar en HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

        # Success → regresa a CLOSED
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout_sec=0.01)
        cb.record_failure("t")
        import time
        time.sleep(0.05)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure("t")
        assert cb.state == CircuitState.OPEN


# ─── ResilientLLMClient ──────────────────────────────────────────────────────

class TestResilientLLMClient:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Respuesta exitosa sin necesidad de retry."""
        client = ResilientLLMClient()
        with patch.object(
            client._base, "generate",
            new=AsyncMock(return_value={"response": "resultado", "context": []})
        ):
            result = await client.generate("prompt test", correlation_id="t-001")

        assert result.success is True
        assert result.response == "resultado"
        assert result.attempts == 1
        assert result.used_fallback is False

    @pytest.mark.asyncio
    async def test_retry_2_fails_then_success(self):
        """2 fallos + 1 éxito = éxito final con attempts=3."""
        client = ResilientLLMClient()
        client._max_attempts = 3
        client._base_delay = 0.001  # Mínimo para test rápido

        call_count = 0

        async def mock_generate(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError(f"Error simulado #{call_count}")
            return {"response": "ok en intento 3", "context": []}

        with patch.object(client._base, "generate", side_effect=mock_generate):
            result = await client.generate("prompt", correlation_id="t-retry")

        assert result.success is True
        assert result.attempts == 3
        assert result.response == "ok en intento 3"

    @pytest.mark.asyncio
    async def test_all_retries_fail_returns_error(self):
        """Todos los intentos fallan → LLMResponse con success=False."""
        client = ResilientLLMClient()
        client._max_attempts = 2
        client._base_delay = 0.001

        with patch.object(
            client._base, "generate",
            new=AsyncMock(side_effect=RuntimeError("Ollama no disponible"))
        ):
            result = await client.generate("prompt", correlation_id="t-fail")

        assert result.success is False
        assert result.error is not None
        assert "no disponible" in result.error.lower() or "Ollama" in result.error

    @pytest.mark.asyncio
    async def test_circuit_open_rejects_immediately(self):
        """Con circuit OPEN, la llamada se rechaza sin intentos al LLM."""
        client = ResilientLLMClient()
        # Abrir el circuit breaker manualmente
        for _ in range(client._cb.failure_threshold):
            client._cb.record_failure("forced")

        assert client._cb.is_open()

        with patch.object(client._base, "generate", new=AsyncMock()) as mock_gen:
            result = await client.generate("prompt", correlation_id="t-open")

        assert result.success is False
        assert "OPEN" in result.error
        mock_gen.assert_not_called()  # No se intentó la llamada

    @pytest.mark.asyncio
    async def test_to_legacy_dict_compat_on_success(self):
        """to_legacy_dict() produce formato compatible con código heredado."""
        client = ResilientLLMClient()
        with patch.object(
            client._base, "generate",
            new=AsyncMock(return_value={"response": "texto extraído", "context": [1, 2]})
        ):
            result = await client.generate("p", correlation_id="t")

        legacy = result.to_legacy_dict()
        assert "response" in legacy
        assert legacy["response"] == "texto extraído"
        assert "error" not in legacy

    @pytest.mark.asyncio
    async def test_to_legacy_dict_on_failure(self):
        """to_legacy_dict() en fallo incluye 'error', 'response' vacío."""
        client = ResilientLLMClient()
        client._max_attempts = 1
        client._base_delay = 0.001
        with patch.object(
            client._base, "generate",
            new=AsyncMock(side_effect=RuntimeError("down"))
        ):
            result = await client.generate("p", correlation_id="t")

        legacy = result.to_legacy_dict()
        assert "error" in legacy
        assert legacy["response"] == ""

    @pytest.mark.asyncio
    async def test_fallback_model_used_when_configured(self):
        """Si LLM_FALLBACK_MODEL está configurado y el principal falla, usa el alternativo."""
        client = ResilientLLMClient()
        client._max_attempts = 1
        client._base_delay = 0.001
        client._fallback_model = "llama3.2:3b"  # Modelo alternativo

        call_models = []

        async def mock_generate(**kwargs):
            model = kwargs.get("model")
            call_models.append(model)
            if model != "llama3.2:3b":
                raise RuntimeError("modelo principal down")
            return {"response": "respuesta del fallback", "context": []}

        with patch.object(client._base, "generate", side_effect=mock_generate):
            result = await client.generate("prompt", correlation_id="t-fallback")

        assert result.success is True
        assert result.used_fallback is True
        assert "fallback" in result.response


# ─── Test de integración: Pipeline legacy compatible ─────────────────────────

class TestLegacyPipelineCompatibility:
    @pytest.mark.asyncio
    async def test_resilient_client_result_compatible_with_legacy_llm_response(self):
        """
        El código heredado que hace result.get('response', '') debe seguir funcionando
        con to_legacy_dict().
        """
        client = ResilientLLMClient()
        with patch.object(
            client._base, "generate",
            new=AsyncMock(return_value={"response": '{"status": "ok"}', "context": []})
        ):
            llm_result = await client.generate("prompt", correlation_id="compat-test")

        # Simular el patrón heredado en analyst.py:
        raw_content = llm_result.to_legacy_dict().get("response", "{}")
        assert raw_content == '{"status": "ok"}'
