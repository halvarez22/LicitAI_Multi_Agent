# Variables de Entorno — LicitAI Backend

> **Hito 9 — Industrialización Mínima**

## Variables Requeridas

| Variable | Descripción | Ejemplo |
|---|---|---|
| `POSTGRES_CONNECTION_STRING` | Cadena de conexión a la base de datos Postgres | `postgresql+asyncpg://user:pass@db:5432/licitai` |
| `OLLAMA_BASE_URL` | URL del servidor Ollama (LLM local) | `http://ollama:11434` |
| `CHROMA_HOST` | Host del servidor ChromaDB | `chromadb` |
| `CHROMA_PORT` | Puerto del servidor ChromaDB | `8000` |

## Variables de Comportamiento

| Variable | Descripción | Default | Producción |
|---|---|---|---|
| `ENVIRONMENT` | Entorno de ejecución | `development` | `production` |
| `ALLOWED_ORIGINS` | Lista separada por comas de orígenes CORS permitidos | `http://localhost:3000` | `https://tu-app.com,https://api.tu-app.com` |
| `LOG_LEVEL` | Nivel de logging (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | Si no se define: `DEBUG` en dev, `INFO` en prod | `INFO` |
| `LICITAI_HTTP_VERBOSE` | Loguear **todas** las respuestas HTTP 2xx/3xx (`1`/`true`/`yes`) | desactivado | opcional |
| `LICITAI_HTTP_QUERY_LOG_MAX` | Caracteres máx. de query string en trazas HTTP | `400` | opcional |
| `LICITAI_UVICORN_ACCESS` | Líneas clásicas de acceso uvicorn (`GET /path 200`) | desactivado | opcional |
| `OLLAMA_NUM_PREDICT` | Máx. tokens de **salida** por llamada a `/api/generate` (JSON largo en compliance, etc.) | `4096` | subir a `8192` si listas masivas truncan |

## Comportamiento según ENVIRONMENT

### `development` (default)
- CORS abierto (`*`)
- Logs en formato legible por consola
- `/docs` y `/redoc` disponibles
- Nivel de log: `DEBUG`

### `production`
- CORS restrictivo: solo orígenes en `ALLOWED_ORIGINS`
- Logs en formato **JSON estructurado** (structlog), compatibles con Datadog, Loki, etc.
- `/docs` y `/redoc` **desactivados**
- Nivel de log: `INFO`
- Headers CORS en errores 500 respetan el origen de la request

## Campos de Log Estructurado (Hito 9)

Cada request a `/api/v1/agents/process` emite dos entradas de log:

```json
// Al inicio
{"event": "orchestrator_start", "session_id": "sess_abc", "company_id": "co_xyz", "mode": "generation_only", "resume": false, "level": "info"}

// Al terminar
{"event": "orchestrator_done", "session_id": "sess_abc", "status": "success", "stop_reason": "GENERATION_COMPLETED", "level": "info"}
```

## Ejemplo docker-compose (fragmento)

```yaml
environment:
  - ENVIRONMENT=production
  - POSTGRES_CONNECTION_STRING=postgresql+asyncpg://licitai:secret@db:5432/licitai
  - ALLOWED_ORIGINS=https://app.licitai.mx,https://api.licitai.mx
  - OLLAMA_BASE_URL=http://ollama:11434
  - CHROMA_HOST=chromadb
  - CHROMA_PORT=8000
```

## Notas de Seguridad

- **Nunca** commitear `.env` con credenciales reales. Usar `.env.example` como plantilla.
- En producción, pasar secretos vía Docker Secrets o un vault (ej. HashiCorp Vault).
- El CORS restrictivo en producción previene llamadas cross-origin no autorizadas desde dominios externos.
