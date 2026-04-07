import os
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.routes import health, agents
from app.api.v1.routes import upload, chatbot, sessions, companies, downloads, feedback, experience
from app.core.logging_config import configure_logging, get_logger

# ================================
# CONFIGURACIÓN DE ENTORNO
# ================================
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Hito 9: Logging JSON estructurado
configure_logging()
logger = get_logger("licitai.main")
_http_verbose = os.getenv("LICITAI_HTTP_VERBOSE", "").lower() in ("1", "true", "yes")
_query_max = int(os.getenv("LICITAI_HTTP_QUERY_LOG_MAX", "400"))

app = FastAPI(
    title="Licitaciones AI API",
    description="API Gateway Enterprise Grade para gestionar Licitaciones con Sistema Multi-Agente RAG local",
    version="1.0.0",
    docs_url="/docs" if ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if ENVIRONMENT != "production" else None,
)

# ================================
# CORS — Hito 9: Restrictivo en producción
# ================================
_DEV_ORIGINS = ["*"]
_PROD_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
allow_origins = _DEV_ORIGINS if ENVIRONMENT != "production" else _PROD_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Trazas HTTP: status, duración y excepciones no capturadas (corrige el “500 sin contexto”)
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    from fastapi.responses import JSONResponse

    start = time.perf_counter()
    method = request.method
    path = request.url.path
    q = request.url.query
    query_snip = (q[:_query_max] + "…") if len(q) > _query_max else q if q else ""

    try:
        response = await call_next(request)
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.error(
            "http_unhandled_exception",
            method=method,
            path=path,
            query=query_snip or None,
            duration_ms=duration_ms,
            error=str(e),
            exc_info=True,
        )
        response = JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Fallo interno del servidor: {str(e)}"},
        )
        origin = request.headers.get("origin", "*")
        response.headers["Access-Control-Allow-Origin"] = origin if ENVIRONMENT == "production" else "*"
        return response

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    status = response.status_code
    log_kw = dict(
        method=method,
        path=path,
        status_code=status,
        duration_ms=duration_ms,
    )
    if query_snip:
        log_kw["query"] = query_snip

    if status >= 500:
        logger.error("http_response", **log_kw)
    elif status >= 400:
        logger.warning("http_response", **log_kw)
    elif _http_verbose:
        logger.info("http_response", **log_kw)

    return response

# ================================
# REGISTRO DE RUTAS / ENDPOINTS
# ================================
app.include_router(health.router, prefix="/api/v1", tags=["Sistema"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Orquestador Multi-Agente"])
app.include_router(upload.router, prefix="/api/v1/upload", tags=["Documentos OCR"])
app.include_router(chatbot.router, prefix="/api/v1/chatbot", tags=["Chat RAG Exploratorio"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["Gestión de Licitaciones"])
app.include_router(companies.router, prefix="/api/v1/companies", tags=["Base de Datos Empresas"])
app.include_router(downloads.router, prefix="/api/v1/downloads", tags=["Descarga de Documentos"])
app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["Feedback HITL"])
app.include_router(experience.router, prefix="/api/v1/experience", tags=["Experiencia y Casos Similares"])

@app.on_event("startup")
async def startup_event():
    logger.info("licitai_startup", environment=ENVIRONMENT, cors_origins=allow_origins)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("licitai_shutdown")
