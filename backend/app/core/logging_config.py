"""
Hito 9: Logging JSON estructurado con structlog.
Emite líneas JSON con session_id, timestamp, level y message.
Funciona con structlog si está instalado; si no, usa el logging estándar como fallback.
"""
import logging
import os
import sys

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")


def _resolve_log_level() -> int:
    """Nivel de log desde LOG_LEVEL (DEBUG/INFO/WARNING/ERROR) o por entorno."""
    name = (os.getenv("LOG_LEVEL") or "").strip().upper()
    if name and name in logging._nameToLevel:
        return logging._nameToLevel[name]
    return logging.DEBUG if ENVIRONMENT == "development" else logging.INFO


def configure_logging():
    """Configura el sistema de logging según el entorno."""
    log_level = _resolve_log_level()

    try:
        import structlog

        # Procesadores compartidos
        shared_processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
        ]

        if ENVIRONMENT == "production":
            # Formato JSON en producción
            renderer = structlog.processors.JSONRenderer()
        else:
            # Formato legible en desarrollo
            renderer = structlog.dev.ConsoleRenderer(colors=True)

        structlog.configure(
            processors=shared_processors + [
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            cache_logger_on_first_use=True,
        )

        # También configurar stdlib para que pase por structlog
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=renderer,
                foreign_pre_chain=shared_processors,
            )
        )
        root_logger = logging.getLogger()
        root_logger.handlers = [handler]
        root_logger.setLevel(log_level)

    except ImportError:
        # Fallback si structlog no está instalado
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stdout,
        )

    # Acceso HTTP de uvicorn (línea tipo GET /path 200); opcional para no duplicar middleware
    access_level = logging.INFO if os.getenv("LICITAI_UVICORN_ACCESS", "").lower() in (
        "1",
        "true",
        "yes",
    ) else logging.WARNING
    logging.getLogger("uvicorn.access").setLevel(access_level)

    # Telemetría Chroma/PostHog: ruido en logs; no afecta al cliente HTTP
    logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
    logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def get_logger(name: str):
    """Devuelve un logger (structlog o stdlib según disponibilidad)."""
    try:
        import structlog
        return structlog.get_logger(name)
    except ImportError:
        return logging.getLogger(name)
