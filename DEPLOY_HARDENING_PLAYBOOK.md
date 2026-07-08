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
- **Piloto HRU (F0–F4)** — ver §8:
  - `LICITAI_ADMIN_ECONOMIC_DEFERRAL`
  - `LICITAI_DECOUPLED_GENERATION_ENABLED`
  - `LICITAI_ECONOMIC_CHAT_FIRST`
  - `LICITAI_ECONOMIC_POST_ANALYSIS_HOOK_ENABLED`
  - `LICITAI_PACKAGING_REQUIRE_ALL_SOBRES`

Comando sugerido:

- `docker compose exec backend python -c "import os; keys=['ENVIRONMENT','LOG_LEVEL','DATABASE_URL','VECTOR_DB_URL','REDIS_URL','LLM_URL','OLLAMA_URL','ECON_TABULAR_FUZZY_THRESHOLD','VALIDATION_STRICT_ENTITIES','COMPRANET_ALLOWED_EXT','COMPRANET_PACKAGE_MAX_BYTES','LICITAI_ADMIN_ECONOMIC_DEFERRAL','LICITAI_DECOUPLED_GENERATION_ENABLED','LICITAI_ECONOMIC_CHAT_FIRST','LICITAI_PACKAGING_REQUIRE_ALL_SOBRES']; print('\n'.join(f'{k}={os.getenv(k)}' for k in keys))"`

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
- **Piloto HRU (F4):** `backend/scripts/smoke_pilot_onprem_hru.py` — suite unificada F0–F3
- **Windows VM:** `backend/scripts/run_pilot_smoke_hru.ps1`

Guía operador: [`docs/GUIA_PILOTO_ONPREM_HRU.md`](docs/GUIA_PILOTO_ONPREM_HRU.md)  
Sign-off: [`docs/PILOT_SIGNOFF_CHECKLIST.md`](docs/PILOT_SIGNOFF_CHECKLIST.md)

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

## 8) Piloto on-premise HRU (F4 — base)

Perfil recomendado en [`backend/app/contracts/pilot_onprem_policy.json`](backend/app/contracts/pilot_onprem_policy.json). Contrato versionado; **sin valores fijos por convocante**.

### 8.1 Flags piloto (defaults recomendados)

| Variable | Piloto | Producción estricta (post sign-off) |
|----------|--------|-------------------------------------|
| `LICITAI_ADMIN_ECONOMIC_DEFERRAL` | `true` | `false` solo si bases exigen tarifa en admin |
| `LICITAI_DECOUPLED_GENERATION_ENABLED` | `true` | `true` |
| `LICITAI_ECONOMIC_CHAT_FIRST` | `true` | `true` |
| `LICITAI_ECONOMIC_POST_ANALYSIS_HOOK_ENABLED` | `true` | `true` |
| `LICITAI_PACKAGING_REQUIRE_ALL_SOBRES` | `false` | `true` si portal exige ZIP completo |

Añadir al `.env` del cliente (ver también [`.env.example`](.env.example)).

### 8.2 Smoke automatizado (VM cliente)

Desde el host o contenedor backend:

```powershell
cd backend
$env:PYTHONPATH='.'
python scripts/smoke_pilot_onprem_hru.py
```

Con API levantada (healthcheck opcional):

```powershell
$env:PILOT_API_BASE='http://127.0.0.1:8001/api/v1'
python scripts/smoke_pilot_onprem_hru.py
```

**Criterio de pase:** salida `SMOKE OK: pilot on-premise F10 (HRU suite F0–F10)`.

La suite ejecuta internamente:

- Validación de contratos JSON (F0–F3 + F6–F9)
- `smoke_economic_chat_capture.py` (F1 + F8 totales)
- `smoke_technical_chat_capture.py` (F9)
- `smoke_decoupled_generation.py` (F2)
- `smoke_dual_stream_concurrency.py` (F6)
- `smoke_isapeg_dual_copilot_e2e.py` (F10 E2E sintético)
- Muestreo UX sin códigos internos (sign-off §4.7)

### 8.3 Capacitación y sign-off

- Guía 1 página (3 flujos): [`docs/GUIA_PILOTO_ONPREM_HRU.md`](docs/GUIA_PILOTO_ONPREM_HRU.md)
- Checklist cliente: [`docs/PILOT_SIGNOFF_CHECKLIST.md`](docs/PILOT_SIGNOFF_CHECKLIST.md)

### 8.4 Rollback piloto

1. Desactivar generación desacoplada: `LICITAI_DECOUPLED_GENERATION_ENABLED=false` (vuelve a modo `full` único).
2. Empaquetado estricto off: mantener `LICITAI_PACKAGING_REQUIRE_ALL_SOBRES=false` hasta revalidar portal.
3. Re-ejecutar smoke F10 tras cualquier cambio de flags.

## 9) Piloto HRU — dual stream y copiloto completo (F6–F10)

Extensión del perfil F4 para REQ-1 (streams paralelos) y REQ-2 (copiloto técnico + totales económicos).

### 9.1 Flags adicionales (piloto)

| Variable | Piloto | Notas |
|----------|--------|-------|
| `LICITAI_DUAL_STREAM_ENABLED` | `true` | Colas `technical` / `economic` en la misma sesión |
| `LICITAI_ECONOMIC_CHAT_CALC_ON_CAPTURE` | `true` | Totales en confirmación de precio (F8) |
| `LICITAI_TECHNICAL_CHAT_FIRST` | `true` | Gate `GENERAR_TECNICA` hasta captura completa |
| `LICITAI_TECHNICAL_POST_ANALYSIS_HOOK_ENABLED` | `true` | Slots técnicos tras análisis |
| `LICITAI_COPILOT_UNIFIED_STATUS` | `true` | Intención «estado dual» en chat |

Con flags en `false`, el sistema conserva comportamiento legacy (sin romper sesiones existentes).

### 9.2 Criterios de aceptación automatizados (CA-2.12 / CA-2.13)

```powershell
cd backend
$env:PYTHONPATH='.'
python scripts/smoke_technical_chat_capture.py
python scripts/smoke_isapeg_dual_copilot_e2e.py
python scripts/smoke_pilot_onprem_hru.py
```

UAT manual recomendado: sesión solo-chat (sin Excel) completando cotización + técnica y lanzando ambos streams.

### 9.3 Rollback F6–F10

1. `LICITAI_DUAL_STREAM_ENABLED=false` — vuelve a cola plana única.
2. `LICITAI_TECHNICAL_CHAT_FIRST=false` — generación técnica sin gate de captura chat.
3. `LICITAI_ECONOMIC_CHAT_CALC_ON_CAPTURE=false` — confirmaciones sin bloque de totales.
4. Re-ejecutar suite F10 antes de cerrar ticket de despliegue.

## 10) Integridad expediente HRU (R1–R5 — readiness + binding + fingerprint)

Normativa: [`docs/SPEC_EXPEDIENTE_READINESS_AND_INTEGRITY_HRU.md`](docs/SPEC_EXPEDIENTE_READINESS_AND_INTEGRITY_HRU.md)  
Handoff UI: [`docs/SPEC_UI_READINESS_INTEGRATION_HRU.md`](docs/SPEC_UI_READINESS_INTEGRATION_HRU.md)

### 10.1 Variables críticas

| Variable | Piloto | Producción | Efecto |
|----------|--------|------------|--------|
| `LICITAI_READINESS_GATES_ENABLED` | `true` | `true` | Gates orquestador + descargas + guided |
| `LICITAI_EXPEDIENTE_GUIDED_ENABLED` | `false` | `true` tras sign-off UI | Barra P0 delegada a readiness |

Añadir al preflight §2:

```powershell
docker compose exec backend python -c "import os; keys=['LICITAI_READINESS_GATES_ENABLED','LICITAI_EXPEDIENTE_GUIDED_ENABLED']; print('\n'.join(f'{k}={os.getenv(k)}' for k in keys))"
```

### 10.2 Smoke R5 (backend, sin UI)

```powershell
cd backend
$env:PYTHONPATH='.'
python scripts/smoke_expediente_readiness_integrity.py
```

Con API levantada y sesión piloto:

```powershell
$env:PILOT_API_BASE='http://127.0.0.1:8001/api/v1'
$env:PILOT_INTEGRITY_SESSION='vigilancia_issste_mayo_v1'
python scripts/smoke_expediente_readiness_integrity.py --session vigilancia_issste_mayo_v1
```

Regresión oracle completa:

```powershell
python -m pytest tests/oracle/test_expediente_readiness_oracle.py tests/test_company_binding_service.py tests/test_artifact_fingerprint_service.py tests/test_generation_wipe_policy.py tests/test_delivery_scope_integrity.py tests/test_orchestrator_decoupled_generation.py -q
```

**Criterio de pase:** `SMOKE OK: expediente readiness + integridad HRU (R5)` + pytest verde.

### 10.3 Factory reset — sesión contaminada (ej. vigilancia_issste)

Procedimiento **sin borrar volúmenes Docker**:

1. Backup estado sesión (export JSON o snapshot DB).
2. `POST /api/v1/sessions/vigilancia_issste/bind-company` con empresa válida (ej. Mayo y Torres `co_1780079004578`).
3. `GET /api/v1/sessions/vigilancia_issste/readiness` — confirmar `binding_valid=true` y blockers de captura/regeneración esperados.
4. Limpiar inputs cross-tender en chat si `capture.cross_tender_contamination=true`.
5. Completar captura económica HITL en chat.
6. Regenerar económica: `generation_mode=economic`.
7. Verificar descarga: `GET /downloads/artifacts?scope=economic` → `readiness_integrity_blocked=false`, RFC coherente.

**Alternativa limpia:** crear sesión nueva `vigilancia_issste_mayo_v1` sin arrastrar outputs jun-2026.

### 10.4 Rollback integridad

| Paso | Acción |
|------|--------|
| 1 | `LICITAI_READINESS_GATES_ENABLED=false` — desactiva gates (solo emergencia; reintroduce riesgo CONTAM01) |
| 2 | Mantener `LICITAI_EXPEDIENTE_GUIDED_ENABLED=false` |
| 3 | Revertir imagen backend al tag pre-R4 si gates causan regresión |
| 4 | Re-ejecutar smoke R5 + suite F10 tras cualquier cambio |

**No desactivar gates en producción** salvo ventana de emergencia documentada; el incidente ISSSTE ocurrió precisamente con múltiples fuentes de verdad sin gate único.

### 10.5 CI — job `integrity-gate`

Antes de merge a rama piloto:

- `pytest tests/oracle/test_expediente_readiness_oracle.py` (OR-01…OR-12)
- `pytest tests/test_delivery_scope_integrity.py` (CONTAM01)
- `python scripts/smoke_expediente_readiness_integrity.py --skip-pytest`
