# LicitAI - Playbook de Deploy y Hardening (Ruta A)

## 1) Preflight de Infraestructura

Ejecutar desde la raíz del repo:

- `docker compose ps`
- `docker compose logs --tail=120 backend`
- `docker compose logs --tail=120 vector-db`
- `docker compose logs --tail=120 database`
- `docker compose logs --tail=120 queue-redis`

Criterio de pase:

- `backend`, `database`, `vector-db`, `queue-redis` en `healthy`.
- Sin reinicios en bucle ni errores de conexión entre servicios.

## 2) Variables críticas de entorno

Validar en runtime del backend:

- Core:
  - `ENVIRONMENT` (producción: `production`)
  - `LOG_LEVEL` (producción: `INFO`)
  - `DATABASE_URL`
  - `VECTOR_DB_URL`
  - `REDIS_URL`
  - `LLM_URL` / `OLLAMA_URL`
- Económico/HITL:
  - `ECON_TABULAR_FUZZY_THRESHOLD`
  - `VALIDATION_STRICT_ENTITIES`
- Empaquetado CompraNet:
  - `COMPRANET_ALLOWED_EXT`
  - `COMPRANET_PACKAGE_MAX_BYTES`

Comando sugerido:

- `docker compose exec backend python -c "import os; keys=['ENVIRONMENT','LOG_LEVEL','DATABASE_URL','VECTOR_DB_URL','REDIS_URL','LLM_URL','OLLAMA_URL','ECON_TABULAR_FUZZY_THRESHOLD','VALIDATION_STRICT_ENTITIES','COMPRANET_ALLOWED_EXT','COMPRANET_PACKAGE_MAX_BYTES']; print('\n'.join(f'{k}={os.getenv(k)}' for k in keys))"`

## 3) Sanity checks de conectividad interna

- `docker compose exec backend python -c "import urllib.request; print('health_check_backend=OK' if urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=5).status==200 else 'health_check_backend=FAIL'); print('health_check_chroma=OK' if urllib.request.urlopen('http://vector-db:8000/api/v1/heartbeat', timeout=5).status==200 else 'health_check_chroma=FAIL')"`

## 4) Smoke funcional recomendado (E2E)

Orden recomendado:

1. Subir PDF de bases + Excel/CSV de costos.
2. Ejecutar `ANALIZAR BASES`.
3. Ejecutar `GENERAR PROPUESTA`.
4. Corregir un precio por chat (`precio de <concepto>: <valor>`).
5. Verificar en UI:
   - Revalidación automática.
   - Badge de procedencia (Chat/Excel/Catálogo).
   - Trazabilidad en panel y respuesta de procedencia en chat.

Scripts de apoyo:

- `backend/scripts/verify_real_generation.py`
- `backend/scripts/test_full_industrial_generation.py`
- `backend/scripts/e2e_chatbot_intake_full_generation.py`
- `backend/scripts/e2e_monitor_job.py`

## 5) Observabilidad y alertas operativas

- Revisar latencia y errores en backend cada ciclo de generación.
- Monitorear:
  - `waiting_for_data` por sesión.
  - bloqueos económicos activos.
  - tiempos por etapa (`datagap`, `compliance`, `economic`, `delivery`).

Nota:

- El endpoint `GET /health` de Ollama puede devolver 404 según build; usar `/api/tags` para disponibilidad efectiva si aplica.

## 6) Rollback rápido (si hay regresión)

1. Congelar nuevas corridas de generación.
2. Revertir imagen/tag de `backend` y `frontend`.
3. Mantener volúmenes de datos (`postgres`, `chroma`, `redis`) sin borrar.
4. Ejecutar limpieza puntual si hay contaminación:
   - `backend/scripts/cleanup_economic_contamination.py`
5. Repetir preflight + smoke mínimo antes de reabrir.

## 7) Resultado de validación local actual (2026-04-16)

- Infraestructura: `OK` (servicios clave `healthy`).
- Conectividad backend/chroma: `OK`.
- Hallazgos:
  - `ENVIRONMENT=development` (para producción cambiar a `production`).
  - Variables no definidas en runtime: `ECON_TABULAR_FUZZY_THRESHOLD`, `VALIDATION_STRICT_ENTITIES`, `COMPRANET_ALLOWED_EXT`, `COMPRANET_PACKAGE_MAX_BYTES` (se usarán defaults internos, pero se recomienda explicitar en producción).
  - `docker-compose.yml` usa campo `version` obsoleto (no bloqueante).
