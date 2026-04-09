# Guía de despliegue — LicitAI

## Requisitos

- Docker y Docker Compose.
- **NVIDIA + driver** si se usa GPU local para Ollama (recomendado).
- **Ollama en el host** (patrón actual del repo): el backend en contenedor llama a `http://host.docker.internal:11434`. Sin Ollama activo, fallan etapas que usan LLM/OCR remoto a esa URL.

## Variables de entorno

1. Partir de [.env.example](../.env.example) en la raíz del repo.
2. Alinear **`DB_USER`** / **`DB_PASSWORD`** con el servicio `database` de `docker-compose.yml` (por defecto en el compose suele usarse `postgres` / `postgres` si no defines otra cosa).
3. Revisar volumen de salidas: en Windows el ejemplo monta **`C:/data:/data`**. Crea la carpeta o cambia la ruta en tu `docker-compose.override.yml` local (no commitear secretos).

## Orquestación Docker

```bash
docker compose up -d --build
```

Servicios típicos:

| Servicio | Rol |
|----------|-----|
| `backend` | FastAPI (`uvicorn`, **workers=1** por diseño VRAM/asyncio) |
| `database` | PostgreSQL |
| `vector-db` | ChromaDB |
| `queue-redis` | Redis |
| `frontend` | Vite/React; `VITE_API_URL` debe apuntar al API en el host (`127.0.0.1:8001`) |

## Ollama en el host

1. Instala Ollama y descarga el modelo referenciado por `OLLAMA_MODEL` (p. ej. `ollama pull llama3.1:8b`).
2. Confirma: `curl http://127.0.0.1:11434/api/tags` desde el host.
3. Dentro del backend, `LLM_URL` / `OLLAMA_URL` / `OCR_URL` deben seguir apuntando a `host.docker.internal:11434` como en `docker-compose.yml`.

## Producción (orientación)

- No usar bind-mount de `./backend:/app` en caliente; construir imagen versionada y fijar tag.
- `ENVIRONMENT=production`, CORS restrictivo (`ALLOWED_ORIGINS` según [backend/ENV_VARS.md](../backend/ENV_VARS.md)).
- Secretos fuera del repo (vault / secrets de orquestador).
- Mantener **`--workers 1`** salvo que se rediseñe el control de concurrencia y VRAM.

## Salud

- Backend: `GET /api/v1/health` (usado por healthcheck del compose).
