# Troubleshooting — LicitAI

## Ollama / LLM

**Síntoma:** timeouts, errores de conexión o compliance vacío.  
**Comprobar:**

1. Ollama en el host: `http://127.0.0.1:11434`.
2. En contenedor backend, URLs `host.docker.internal:11434` (Windows/Mac Docker Desktop).
3. Modelo descargado: coincide con `OLLAMA_MODEL` en `docker-compose.yml` / entorno.

## VRAM / lentitud extrema

**Síntoma:** compliance muy lento o Ollama saturado.  
**Contexto:** el compose fija **`uvicorn --workers 1`** a propósito.  
**Acciones:** reducir paralelismo en compliance (`COMPLIANCE_MAX_CONCURRENT_CHUNKS=1` ya es el patrón estable), revisar `COMPLIANCE_CHUNK_*` y no ejecutar otros consumidores GPU intensivos en paralelo.

## `latest_job.json` no aparece

**Causa habitual:** el orquestador no llegó a ejecutar la persistencia al cierre (proceso abortado, contenedor reiniciado a mitad de job).  
**Acción:** revisar logs `docker compose logs backend` y reejecutar la sesión.

## Export Oracle falla (`Faltan stages`)

**Síntoma:** `export_oracle_inputs.py` código `3`.  
**Causa:** en PostgreSQL no hay `stage_completed:analysis|compliance|economic` para esa sesión.  
**Acción:** confirmar `session_id` y que el pipeline llegó a esas etapas (p. ej. descalificación en gate antes de economic → faltará economic).

## Pytest local falla en `TestClient` / `httpx`

**Síntoma:** `AttributeError: module 'httpx' has no attribute 'BaseTransport'`.  
**Causa:** mezcla de versiones `httpx` / `starlette` en el venv del host.  
**Acción:** usar entorno limpio con `pip install -r requirements.txt` o tomar **CI como referencia**.

## Frontend no llega al API

**Síntoma:** CORS o red vacía.  
**Comprobar:** `VITE_API_URL` apunta a `http://127.0.0.1:8001/api/v1` (no al nombre Docker `backend` desde el navegador).

## Chroma / PostgreSQL

**Síntoma:** errores de conexión al arrancar.  
**Acción:** esperar healthchecks del compose; revisar `DATABASE_URL` y `VECTOR_DB_URL` frente a nombres de servicio (`database`, `vector-db`).
