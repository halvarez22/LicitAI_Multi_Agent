# Variables de Entorno — LicitAI Backend

> **Hito 9 — Industrialización Mínima**

**Fuente de verdad para el stack Docker actual:** [.env.example](../.env.example) en la raíz del repo (nombres `DATABASE_URL`, `LLM_URL`, `OLLAMA_URL`, compliance, CompraNet, Redis). Este archivo amplía el detalle de comportamiento por `ENVIRONMENT`.

## Variables Requeridas

| Variable | Descripción | Ejemplo |
|---|---|---|
| `DATABASE_URL` | Postgres (sync URL en settings; async en código donde aplique) | `postgresql://postgres:postgres@database:5432/licitaciones` |
| `LLM_URL` / `OLLAMA_URL` | Ollama (host: `http://host.docker.internal:11434` desde contenedor) | `http://host.docker.internal:11434` |
| `VECTOR_DB_URL` | Chroma en red Docker | `http://vector-db:8000` |

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
| `OLLAMA_NUM_CTX` | Ventana de contexto enviada en `options.num_ctx` a Ollama (`llm_service`) | `12288` | ver `infra/ollama/` Modelfiles |

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
  - DATABASE_URL=postgresql://licitai:secret@database:5432/licitaciones
  - ALLOWED_ORIGINS=https://app.licitai.mx,https://api.licitai.mx
  - LLM_URL=http://ollama:11434
  - VECTOR_DB_URL=http://vector-db:8000
```

## Notas de Seguridad

- **Nunca** commitear `.env` con credenciales reales. Usar `.env.example` como plantilla.
- En producción, pasar secretos vía Docker Secrets o un vault (ej. HashiCorp Vault).
- El CORS restrictivo en producción previene llamadas cross-origin no autorizadas desde dominios externos.
