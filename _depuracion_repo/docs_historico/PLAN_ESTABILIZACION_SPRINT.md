# Plan de estabilización — sprint por checkpoints

**Objetivo:** Las 3 licitaciones de referencia abren con paneles poblados (hitos, documentos, formatos, junta), re-análisis no vacía la UI, y cada entrega pasa smoke antes de la siguiente.

**Sesiones referencia (obligatorias en cada gate):**
- `isapeg_servicios_de_limpieza`
- `unaq-2026_paneles_solares`
- `vigilancia_issste`

**Reglas del sprint**
1. **Congelar features nuevas** hasta cerrar P0–P2.
2. **Un checkpoint = un merge/commit** con smoke en verde.
3. **Gate mínimo** tras cada tarea (local o Docker):
   ```bash
   cd backend
   python -m pytest tests/test_submission_checklist.py tests/test_session_bases_analysis_invalidation.py -q
   PYTHONPATH=. python scripts/smoke_session_stability.py
   ```
4. **Gate ampliado** (P2+): script `smoke_ui_artifacts.py` (por crear) + curl dictamen/checklist/junta en las 3 sesiones.
5. **Rollback:** si smoke falla en una sesión que antes pasaba → revertir el checkpoint, no parchear encima.

**Estado inicial**
- [x] **P0-00** Fix recursión checklist (`submission_checklist_service.py` + test).

---

## P0 — UI siempre visible (prioridad cliente)

### P0-01 · Calendario independiente del dictamen monolítico
**Problema:** Hitos solo llegan si `/dictamen` (~1.7 MB, lento) termina bien.

**Trabajo**
- [x] En `App.jsx`: `GET /submission-checklist` en paralelo a `fetchDictamen` al montar sesión.
- [x] Estado `submissionChecklist` propio; preview y pestaña calendario lo usan primero.
- [x] Timeout checklist: 30 s; mensaje UX si falla (no pantalla en blanco).
- [x] `SubmissionChecklistPanel`: `active`, sync por `sessionId`, sync al marcar hitos.

**Criterio de aceptación** ✅ (2026-06-06)
- Hitos visibles en preview sin esperar dictamen (API paralela).
- ISAPEG / UNAQ / VIGILANCIA: ≥6 hitos vía `/submission-checklist`.

**Checkpoint:** `checkpoint/p0-01-calendario-api` ✅

---

### P0-02 · Carga paralela de paneles (junta + candidatos ligeros)
**Problema:** Junta ya tiene GET propio; documentos/formatos dependen de dictamen.

**Trabajo**
- [x] Endpoint `GET /sessions/{id}/document-candidates-summary` (corporate physical).
- [x] Endpoint `GET /sessions/{id}/pliego-formats-panel` (formatos por sobre).
- [x] Frontend: pestañas Documentos / Formatos / Junta cargan APIs al abrir pestaña (lazy).
- [x] Junta: `active` por pestaña; ya no depende de `fechaAuditoria` del dictamen.

**Criterio de aceptación** ✅ (2026-06-06)
- VIGILANCIA: docs=6, formatos=27, junta=5 (&lt;2 s salvo junta rebuild).
- UNAQ: docs=10, formatos=9, junta=3.
- ISAPEG: docs=20, formatos=16, junta=4.

**Checkpoint:** `checkpoint/p0-02-paneles-ligeros` ✅

---

### P0-03 · Timeouts y fail-soft en rutas caras del backend
**Problema:** Worker único (`workers=1` por VRAM): una ruta colgada tumba todo.

**Trabajo**
- [x] En `ensure_session_cronograma_and_checklist`: si no hay cronograma en analysis, devolver checklist persistido **sin** RAG (fix parcial ya hecho — revisar que enrichment no corra en bucle).
- [x] Tope de tiempo en enrichment RAG del cronograma (ej. 12 s) → fallback checklist cacheado + log `cronograma_enrichment_timeout`.
- [x] En `GET /dictamen`: no llamar enrichment síncrono pesado si checklist ya válido; submission_checklist vía `get_submission_checklist(refresh_placeholders=False)` cuando aplique.

**Criterio de aceptación** ✅ (2026-06-06)
- `GET /dictamen` en VIGILANCIA <10 s (mediana 3 corridas).
- Ningún log `maximum recursion depth` ni request >120 s en logs.

**Gate:** script timing (por crear en P2) + pytest checklist.

**Checkpoint:** `checkpoint/p0-03-timeouts` ✅

---

## P1 — Rehidratación post re-análisis

### P1-01 · Servicio `rehydrate_analysis_artifacts`
**Problema:** Tras invalidación/re-análisis quedan compliance pero no junta/dictamen/fechas coherentes.

**Trabajo**
- [x] `backend/app/services/analysis_artifacts_rehydrate_service.py`
- [x] Script `scripts/rehydrate_analysis_artifacts.py` (`--session`, `--all-reference`)
- [x] Tests `tests/test_analysis_artifacts_rehydrate_service.py` (4 tests)

**Criterio de aceptación** ✅ (2026-06-06)
- VIGILANCIA: hitos=6, junta=5, sobre_1=31, `economic_user_inputs`=8 intactos.
- UNAQ / ISAPEG: success=true, snapshot committed, HITL/generación preservados.
- `--all-reference`: 3/3 OK.

**Checkpoint:** `checkpoint/p1-01-rehydrate-service` ✅

---

### P1-02 · Invocar rehidratación al cerrar análisis
**Trabajo**
- [x] Tras `stage_completed:compliance` → `rehydrate_after_analysis_pipeline` (await).
- [x] Eliminada junta duplicada post-analysis; commit snapshot vía rehydrate.
- [x] Upload: rehydrate si bases no invalidaron y faltan artefactos / `pending_reanalysis`.
- [x] Fallo → `ANALYSIS_REHYDRATE_INCOMPLETE` + `rehydrate_last_error`.

**Criterio de aceptación** ✅ (2026-06-06)
- Cadena única P1-01 integrada en orquestador.
- Test stop_reason en pipeline hook (5 tests rehydrate OK).

**Checkpoint:** `checkpoint/p1-02-orchestrator-hook` ✅

---

### P1-03 · Reparar sesiones ya rotas (one-shot)
**Trabajo**
- [x] Ejecutado `rehydrate_analysis_artifacts.py --all-reference` (2026-06-06).
- [x] ISAPEG / UNAQ / VIGILANCIA: hitos=6, junta≥3, snapshot committed, HITL preservado.

**Checkpoint:** `checkpoint/p1-03-repair-production-sessions` ✅

---

## P2 — Red anti-regresión

### P2-01 · Ampliar `smoke_session_stability.py`
**Trabajo**
- [x] Checks: hitos≥6, junta≥1, dictamen, sobre_1_tecnico, checklist <5s, AT_RISK sin recursión.
- [x] Exit 2 si MISSING / RecursionError / timeout checklist.
- [x] Tests `tests/test_smoke_session_stability.py` (5 tests).
- [x] Flags `--min-hitos`, `--checklist-timeout`.

**Criterio de aceptación** ✅ (2026-06-06)
- Docker: 3/3 verdict OK; VIGILANCIA `checklist_at_risk=true` en 0.13s sin FAIL.

**Checkpoint:** `checkpoint/p2-01-smoke-extended` ✅

---

### P2-02 · Baseline anonimizado por sesión referencia
**Trabajo**
- [x] `tests/fixtures/real_sessions/baseline_artifacts_*.json` (3 sesiones, solo conteos).
- [x] `app/services/reference_session_baseline.py` + `scripts/capture_reference_baseline.py`.
- [x] `tests/test_reference_sessions_baseline.py` (unit + integration live).

**Criterio de aceptación** ✅ (2026-06-06)
- Unit: 3/3 passed; live Docker `LICITAI_REFERENCE_BASELINE_LIVE=1`: 3 sesiones ≥ baseline.

**Checkpoint:** `checkpoint/p2-02-baseline-tests` ✅

---

### P2-03 · Script `smoke_ui_artifacts.py` (HTTP)
**Trabajo**
- [x] GET checklist, junta, document-candidates-summary, pliego-formats-panel, dictamen.
- [x] `--base-url http://127.0.0.1:8001` + `--all-reference`.
- [x] Validación vs baseline P2-02; tests unitarios (4).

**Criterio de aceptación** ✅ (2026-06-06)
- Host → Docker 8001: 3/3 verdict OK.

**Checkpoint:** `checkpoint/p2-03-http-smoke` ✅

---

### P2-04 · Endpoint `GET /sessions/{id}/health`
**Trabajo**
- [x] `session_health_service.py` — artifacts, stale, rehydrate_recommended.
- [x] `GET /sessions/{id}/health` + `POST /sessions/{id}/rehydrate-analysis-artifacts`.
- [x] Banner frontend con botón «Actualizar artefactos».
- [x] Tests service + routes (5).

**Criterio de aceptación** ✅ (2026-06-06)
- 3 referencias: `healthy=true`, `rehydrate_recommended=false`.
- POST rehydrate idempotente vía pipeline P1-02.

**Checkpoint:** `checkpoint/p2-04-health-endpoint` ✅

---

## P3 — Resiliencia operativa (sin romper VRAM)

> **Nota:** `docker-compose` mantiene `workers=1` por semáforo VRAM. No subir workers sin revisar GPU; mitigar con timeouts y APIs ligeras (P0).

### P3-01 · Cola / job para re-análisis largo
**Trabajo**
- [x] Re-análisis vía job async existente (`POST /agents/process` + polling UI).
- [x] Rehydrate pesado vía job async (`POST .../rehydrate-analysis-artifacts` → 202 + poll `/agents/jobs/{id}/status`).
- [x] Thread aislado en `session_maintenance_job_service` (no bloquea GET ligeros).
- [x] Modo `?sync=true` para scripts CLI.

**Checkpoint:** `checkpoint/p3-01-async-reanalysis` ✅

---

### P3-02 · Documentar política de invalidación
**Trabajo**
- [x] [`docs/ARTIFACT_LIFECYCLE.md`](ARTIFACT_LIFECYCLE.md): qué se borra, qué se conserva, quién reconstruye.
- [x] Checklist pre-merge: [`docs/PR_CHECKLIST_ESTABILIDAD.md`](PR_CHECKLIST_ESTABILIDAD.md).

**Checkpoint:** `checkpoint/p3-02-docs` ✅

---

## P4 — Generación VIGILANCIA (después de P0–P2)

### P4-01 · Resolver `INCOMPLETE_FORMATS_DATA`
**Trabajo**
- [x] Diagnosticar 2 docx (Anexo 14 contrato, Anexo 9 cotización): placeholders vs datos empresa.
- [x] Completar vía HITL chat o relanzar `resume_session_generation.py` mode `generation_only`.
- [x] Verificar propuesta económica en disco + packager.

**Criterio:** generación formats → economic → packager sin stop en formatos (o HITL explícito documentado). ✅ VIGILANCIA `FINAL_OK`.

**Checkpoint:** `checkpoint/p4-01-vigilancia-generation` ✅

---

## P5 — Entrega cliente

### P5-01 · Demo script + informe
- [x] Checklist de demo (3 sesiones, qué mostrar en cada pestaña) → [`docs/DEMO_CLIENTE_3_SESIONES.md`](DEMO_CLIENTE_3_SESIONES.md)
- [x] Informe 1 página: qué se estabilizó, qué queda en backlog, cómo correr smoke → [`docs/INFORME_ESTABILIZACION_HANDOFF.md`](INFORME_ESTABILIZACION_HANDOFF.md)

**Checkpoint:** `checkpoint/p5-01-handoff` ✅

---

## Orden de ejecución recomendado

```
P0-00 ✅ → P0-01 → P0-02 → P0-03 → P1-01 → P1-02 → P1-03
         → P2-01 → P2-02 → P2-03 → P2-04
         → [demo cliente]
         → P4-01 (VIGILANCIA generación)
         → P3-* y P5-* según tiempo
```

## Qué NO hacer en este sprint

- Nuevas reglas por licitación (hardcode).
- Refactor total de `session_data` a microservicios.
- Cambiar modelos LLM o prompts masivos sin baseline.
- Subir `uvicorn workers` sin plan VRAM.

---

## Registro de checkpoints (rellenar al avanzar)

| Checkpoint | Fecha | Responsable | Smoke OK | Notas |
|------------|-------|-------------|----------|-------|
| P0-00 | | | ☐ | Recursión checklist |
| P0-01 | 2026-06-06 | Agent | ☑ | Calendario API paralela |
| P1-03 | 2026-06-06 | Agent | ☑ | Rehydrate 3 sesiones |
| P2-04 | 2026-06-06 | Agent | ☑ | Health + banner UI |
| P0-02 | | | ☐ | |
| … | | | | |
