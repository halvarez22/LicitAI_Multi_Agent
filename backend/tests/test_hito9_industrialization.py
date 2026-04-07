import pytest
import os
from unittest.mock import patch


def test_cors_development_allows_all():
    """Hito 9: En desarrollo, CORS debe permitir todos los orígenes."""
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
        # Simular reload del módulo para capturar la variable de entorno
        import importlib
        import app.main as main_module
        importlib.reload(main_module)
        # allow_origins = ["*"] en dev
        assert main_module.allow_origins == ["*"]


def test_cors_production_uses_env_var():
    """Hito 9: En producción, CORS usa ALLOWED_ORIGINS de la variable de entorno."""
    with patch.dict(os.environ, {
        "ENVIRONMENT": "production",
        "ALLOWED_ORIGINS": "https://app.licitai.mx,https://api.licitai.mx"
    }):
        import importlib
        import app.main as main_module
        importlib.reload(main_module)
        assert "https://app.licitai.mx" in main_module.allow_origins
        assert "https://api.licitai.mx" in main_module.allow_origins
        assert "*" not in main_module.allow_origins


def test_logging_config_imports_without_error():
    """Hito 9: El módulo de logging debe importar sin errores con o sin structlog."""
    from app.core.logging_config import configure_logging, get_logger
    # No debe lanzar excepción
    configure_logging()
    log = get_logger("test.hito9")
    assert log is not None


def test_get_logger_returns_usable_logger():
    """Hito 9: get_logger debe devolver un objeto con método info."""
    from app.core.logging_config import get_logger
    log = get_logger("licitai.test")
    # Verificar que es usable (no lanza excepción al llamar info)
    log.info("test_log_entry", session_id="sess_test", status="ok")
