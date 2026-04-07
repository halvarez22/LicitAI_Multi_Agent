# DICTAMEN TÉCNICO — Falla E2E por Timeout en ISSSTE BCS
## v1.2 — Pulido técnico y criterios de aceptación
## Análisis Definitivo y Propuesta de Solución Integral

**Documento:** `docs/DICTAMEN_TIMEOUT_ISSSTE_BCS.md`
**Fecha:** 2026-03-31
**Elaborado por:** Claude (con validación de análisis tripartito: Claude + Antigravity + Cursor)
**Estado:** CERRADO — Acciones pendientes de implementación

---

## 1. Hallazgo: Dictamen Forense del Timeout

### 1.1 Causa Raíz Confirmada

**El timeout NO fue causado por un bug de código.** Fue una **insuficiencia de la ventana síncrona HTTP** ante una workload de procesamiento forense real.

```
Cronología reconstruida:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
17:37:10 — Inicio de corrida (create_session + upload + process) ✅
17:37:XX — /agents/process inicia
             ├─ Auto-ingesta: SALTADA (doc ya ANALYZED — línea 85 upload.py) ✅
             ├─ Analyst: procesa requisitos ✅
             ├─ Compliance: Map-Reduce en 4 zonas × N bloques LLM
             │    └─ Ollama con llama3.1:8b en RTX 4060 8GB
             │    └─ Cada zona hace múltiples llamadas LLM con contexto
             │    └─ KV cache thrashing progresivo por contexto denso
             └─ Economic: evaluación económica
18:18:04 — Timeout de cliente HTTP tras 2,410s (40 min)
             └─ El backend seguía vivo y trabajando
```

### 1.2 Lo que NO fue (corrección a análisis iniciales)

| Hipótesis descartada | Por qué |
|---|---|
| Bug de re-ingesta redundante | **Descartado por Cursor con evidencia de código.** El doc ya era `ANALYZED` — la auto-ingesta se saltó (línea 85-88 upload.py) |
| Backend colgado | **Descartado.** Logs confirman actividad continua de Ollama |
| Memory leak o deadlock | **Descartado.** El proceso era sano — solo lento |

### 1.3 Lo que SÍ es (causa real)

> **El Compliance Agent con Map-Reduce de 4 zonas está siendo genuinamente exhaustivo en el análisis forense de un documento denso, y el tiempo de procesamiento real excede la ventana HTTP síncrona de 2,410s disponible.**

El sistema **está funcionando correctamente desde la perspectiva forense**. El problema es que una conexión HTTP no es el transporte adecuado para tareas de 40+ minutos.

---

## 2. Estado Actual del Checkpoint (Auditoría de lo Existente)

### 2.1 Lo que SÍ existe

El sistema YA tiene persistencia por hito a nivel de agente:

| Agente | ¿Graba en tasks_completed? | ¿Cuándo? | Contenido |
|---|---|---|---|
| AnalystAgent | ✅ Sí (línea 206-210 analyst.py) | Al terminar análisis | extracted_data completo |
| ComplianceAgent | ✅ Sí (línea 222 compliance.py) | Al terminar las 4 zonas | master_compliance_list + zone_reports + block_events |
| EconomicAgent | ✅ Sí (línea 131 economic.py) | Al terminar evaluación | economic_proposal |
| TechnicalWriter | ✅ Sí (línea 199) | Al terminar escritura | result_data |
| Formats | ✅ Sí (línea 179) | Al terminar formatos | result_data |

### 2.2 Lo que NO existe (gap crítico)

**El Orchestrator NO graba checkpoint entre stages.**

```
Orchestrator.process() — flujo actual:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Analyst ──→ [ejecuta] ──→ [fin] ──→ Compliance ──→ [fin] ──→ Economic ──→ [fin] ──→ ...
                      │
                      └─► record_task_completion ✅ (analyst.py graba)
                                                    │
                                        ❌ Orchestrator NO graba aquí

Compliance ──→ [ejecuta 4 zonas] ──→ [fin] ──→ Economic
                              │
                              └─► record_task_completion ✅ (compliance.py graba)
                                                          │
                                              ❌ Orchestrator NO graba aquí
```

**Implicación:** Si el `/agents/process` falla a mitad de Compliance, la próxima vez que el usuario llame `/agents/process` con `resume_generation=True`:
1. El `resume_generation` flag existe en `AgentInput` (línea 101 orchestrator.py) pero **no se usa para nada** en el flujo actual
2. El Orchestrator reinicia todo desde cero
3. Los datos de `tasks_completed` están grabados pero nadie los lee para retomar

---

## 3. Solución Definitiva y Detallada

### 3.1 taxonomy de cambios por urgencia

```
┌─────────────────────────────────────────────────────────────────┐
│                    JERARQUÍA DE SOLUCIONES                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  CAPA 0 — INMEDIATA (evita que el cliente se desconecte)      │
│  ├── [A] Subir timeout del cliente E2E a 7200s                │
│  └── [B] Verificar que healthcheck no mate contenedor          │
│       → Patch transitorio mientras se implementa arquitectura    │
│       → NOTA: El healthcheck no fue causal del timeout actual   │
│                                                                 │
│  CAPA 1 — ARQUITECTÓNICA TRANSITORIA                           │
│  ├── [1] Convertir /agents/process en endpoint ASYNC            │
│  │        → 202 Accepted + job_id inmediato                     │
│  ├── [2] Background task que ejecuta el Orchestrator            │
│  ├── [3] GET /jobs/{job_id}/status con progreso por stage     │
│  └── [4] Redis como cola de jobs (jobs en lugar de socket)      │
│        NOTA: [1]-[3] son transitorias (BackgroundTasks).        │
│              [4] es el puente hacia solución industrial (RQ).    │
│                                                                 │
│  CAPA 1B — SOLUCIÓN INDUSTRIAL (RQ persistente)                │
│  ├── [R1] Reemplazar BackgroundTasks por RQ (cola durable)       │
│  │        → Jobs sobreviven a reinicios del proceso             │
│  ├── [R2] Reintentos automáticos con política configurable      │
│  └── [R3] Estado durable en Redis con TTL configurable           │
│                                                                 │
│  CAPA 2 — RESUMIBLE (persistencia de estado real)              │
│  ├── [5] Orchestrator.graba checkpoint DESPUÉS de cada stage   │
│  │        → No al final, sino en cada milestone                 │
│  ├── [6] resume_generation realmente retoma desde último hito   │
│  └── [7] MCP graba cada zone de Compliance por separado       │
│                                                                 │
│  CAPA 3 — OPTIMIZACIÓN (reduce tiempo de procesamiento)        │
│  ├── [8] Reducir agentes L3 → GenerationFactory                 │
│  │        → Libera VRAM para Ollama                            │
│  ├── [9] Chunking optimizado para llama3.1:8b (2k tokens)      │
│  └── [10] WebSocket para progreso en tiempo real                │
│                                                                 │
│  CAPA 4 — FORENSE (blindar exactitud)                          │
│  ├── [11] ForensicAuditor con prompt de rigor fiscalista        │
│  └── [12] ForensicAuditorOutput con extracted_quotes obligatorios│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Especificación Detallada por Cambio

---

#### CAMBIO [A] — Timeout inmediato del cliente (5 minutos)

**Qué:** Subir el timeout del script E2E de 2,410s a 7,200s (2 horas).

**Dónde:** En el comando de ejecución del script batch.

**Por qué:** Como patch mientras se implementa la solución arquitectónica. El backend no va a morir porque el cliente espere más — el problema es que el cliente se desconecta antes.

```powershell
# Antes
timeout=2410

# Después
$env:E2E_ORCH_TIMEOUT_SEC="7200"
```

---

#### CAMBIO [B] — Verificación de healthcheck

**Qué:** Verificar que el healthcheck del backend no esté matando el contenedor durante procesamiento largo.

**Dónde:** `docker-compose.yml` — backend healthcheck.

**Nota:** En la corrida ISSSTE BCS no hay evidencia de que el healthcheck haya sido el causante. Se incluye como revisión de robustez, no como corrección del timeout actual.

---

### CAPA 1B — SOLUCIÓN INDUSTRIAL (no solo transitoria)

> ⚠️ **NOTA DE ARQUITECTURA (agregada tras validación de Cursor):**
>
> BackgroundTasks de FastAPI resuelve el problema inmediato de timeout HTTP, pero tiene una limitación: si el proceso/worker de FastAPI cae o se reinicia, el job en memoria se pierde.
>
> Para robustez de grado industrial, el roadmap debe incluir una **cola de jobs persistente**:

| Opción | Complejidad | Robustez | Recomendación |
|---|---|---|---|
| **RQ (Redis Queue)** | Baja | Alta | ✅ Recomendado para este stack |
| **Celery + Redis/Broker** | Media | Muy alta | Para escalamiento futuro |
| **Celery + RabbitMQ** | Alta | Muy alta | Solo si hay múltiples workers |
| **BackgroundTasks (actual)** | Mínima | Baja | Solo como transición rápida |

**Arquitectura objetivo con RQ:**

```
Cliente → POST /agents/process → 202 + job_id
                                 │
                    ┌─────────────▼──────────────┐
                    │  Redis Queue (RQ)          │
                    │  job_id → orchestrator      │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  Worker (proceso separado)  │
                    │  Ejecuta Orchestrator        │
                    │  Checkpointa por stage       │
                    │  Recupera ante falla         │
                    └─────────────┬──────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │  Redis: estado durable      │
                    │  GET /jobs/{id}/status     │
                    └────────────────────────────┘
```

**El checkpoint transaccional por stage es la pieza clave** — con jobs persistentes, si un worker cae, el job se reintenta automáticamente desde el último checkpoint.

---

#### CAMBIO [1] — /agents/process ASYNC (Endpoint 202)

**Qué:** El endpoint `/agents/process` retorna `202 Accepted` con un `job_id` inmediatamente, sin esperar el procesamiento.

**Dónde:** `backend/app/api/v1/routes/agents.py`

```python
@router.post("/process", response_model=GenericResponse)
async def process_licitation_bases(
    request: ProcessBasesRequest,
    background_tasks: BackgroundTasks
):
    memory = MemoryAdapterFactory.create_adapter()
    await memory.connect()

    # Validar documentos analizados
    docs = await memory.get_documents(request.session_id)
    analyzed = [d for d in docs if d.get("content", {}).get("status") == "ANALYZED"]
    if not analyzed:
        await memory.disconnect()
        raise HTTPException(status_code=409, detail="No hay documentos analizados")

    # Crear job
    job_id = str(uuid.uuid4())
    job_state = {
        "job_id": job_id,
        "session_id": request.session_id,
        "status": "QUEUED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "company_data": request.company_data,
        "progress": {"stage": None, "pct": 0}
    }

    # Guardar job en Redis
    redis_client.set(f"job:{job_id}", json.dumps(job_state))
    redis_client.expire(f"job:{job_id}", 86400)  # 24h TTL

    # Encolar tarea en background
    background_tasks.add_task(
        _run_orchestrator_job,
        job_id,
        request.session_id,
        request.company_data
    )

    await memory.disconnect()
    return GenericResponse(
        success=True,
        message=f"Job {job_id} encolado. Consultar estado en GET /jobs/{job_id}",
        data={"job_id": job_id}
    )
```

---

#### CAMBIO [2] — Background Task con logging de progreso

```python
async def _run_orchestrator_job(job_id: str, session_id: str, company_data: dict):
    """Ejecuta el orchestrator en background y actualiza estado en Redis."""
    from app.agents.orchestrator import OrchestratorAgent
    from app.agents.mcp_context import MCPContextManager
    from app.memory.factory import MemoryAdapterFactory

    try:
        # Actualizar estado: RUNNING
        _update_job_status(job_id, "RUNNING", {"stage": "starting"})

        memory = MemoryAdapterFactory.create_adapter()
        await memory.connect()
        mcp_manager = MCPContextManager(memory_repository=memory)
        orchestrator = OrchestratorAgent(context_manager=mcp_manager)

        # Ejecutar con checkpoints por stage
        result = await orchestrator.process(
            session_id=session_id,
            input_data={"company_data": company_data}
        )

        # Actualizar estado: COMPLETED
        _update_job_status(job_id, "COMPLETED", {
            "stage": "done",
            "pct": 100,
            "result_summary": {
                "status": result.get("status"),
                "stop_reason": result.get("orchestrator_decision", {}).get("stop_reason")
            }
        })

        await memory.disconnect()

    except Exception as e:
        _update_job_status(job_id, "FAILED", {
            "error": str(e),
            "forensic_traceback": {
                "last_stage": job_state.get("progress", {}).get("stage"),
                "last_zone": job_state.get("progress", {}).get("zone"),
                "last_block": job_state.get("progress", {}).get("block"),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })
        logger.error("job_failed_forensic", job_id=job_id, error=str(e))
```

---

#### CAMBIO [3] — GET /jobs/{job_id}/status

```python
@router.get("/jobs/{job_id}/status", response_model=GenericResponse)
async def get_job_status(job_id: str):
    """Retorna el estado actual de un job encolado."""
    job_data = redis_client.get(f"job:{job_id}")
    if not job_data:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    job = json.loads(job_data)
    return GenericResponse(success=True, data=job)
```

---

#### CAMBIO [5] — Checkpoint por stage en Orchestrator

**Gap actual:** El Orchestrator solo graba `last_orchestrator_decision` al final (línea 252 orchestrator.py).

**Solución:** Grabar checkpoint DESPUÉS de cada stage exitoso.

```python
# En orchestrator.py, después de cada stage exitoso:

# Después de Analyst (línea 145)
await self.context_manager.record_task_completion(
    session_id=session_id,
    task_name="stage_completed:analyst",
    result={
        "stage": "analysis",
        "status": "completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_summary": {"keys": list(execution_results.get("analysis", {}).get("data", {}).keys())}
    }
)

# Después de Compliance (línea 157)
for zone_result in zone_reports:
    await self.context_manager.record_task_completion(
        session_id=session_id,
        task_name=f"zone_completed:{zone_result['zone']}",
        result={
            "stage": "compliance",
            "zone": zone_result['zone'],
            "status": zone_result['status'],
            "reason": zone_result.get("reason"),
            "metrics": zone_result.get("metrics", {}),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    )
```

---

#### CAMBIO [6] — resume_generation funcional

**Gap actual:** El flag existe pero no se usa.

**Solución:** Que el OrchestratorLea `tasks_completed` al inicio y retome desde el último stage no completado.

```python
async def process(self, session_id: str, input_data: Dict[str, Any]) -> Dict:
    # ... código existente de inicialización ...

    # NUEVO: Si resume_generation=True, leer último checkpoint
    if agent_input.resume_generation:
        session_data = await self.context_manager.memory.get_session(session_id)
        tasks = session_data.get("tasks_completed", []) if session_data else []

        # Encontrar último stage completado
        completed_stages = set()
        for t in tasks:
            task_name = t.get("task", "")
            if task_name.startswith("stage_completed:"):
                completed_stages.add(task_name.split(":", 1)[1])

        # Adjust pipeline_config para saltar stages completados
        if "analysis" in completed_stages:
            stages_skipped.append("analysis")
            logger.info("resume: skipping completed analysis stage")
        if "compliance" in completed_stages:
            stages_skipped.append("compliance")
            logger.info("resume: skipping completed compliance stage")
        # ... etc ...
```

---

#### CAMBIO [8] — Reducción de Agentes L3

**详见:** `docs/REFACTORIZACION_DE_AGENTES.md` sección 4 (GenerationFactory).

**Impacto en timeout:** Menos agentes = menos coordinación Redis = más VRAM para Ollama = procesamiento más rápido.

---

#### CAMBIO [9] — Chunking optimizado para 8GB VRAM

**Problema:** Con `llama3.1:8b` y chunks de 8k tokens, el KV cache se satura en documentos densos, causando thrashing.

**Solución:** Reducir chunks a ~2k tokens.

```python
# compliance.py — cambiar chunk_size
chunk_size = int(os.getenv("COMPLIANCE_CHUNK_CHARS", "2000"))  # Antes: 8000
```

Esto hace más llamadas LLM pero cada una es más rápida porque no hay thrashing de contexto. El tiempo total puede bajar significativamente.

---

## 4. Plan de Ejecución Recomendado

> **Aclaración sobre robustez (v1.1):** Se distinguen dos fases — solución rápida (BackgroundTasks) y solución industrial (RQ/cola persistente). Ambas son válidas; se presentan juntas para que el equipo elija según recursos disponibles.

### Fase Transición — Solución Rápida (1-2 días)

```
1. [A] + [B] — Timeout patch (30 min)
   └─ Subir timeout cliente a 7200s

2. [1] + [2] + [3] — Async endpoint con BackgroundTasks (2 horas)
   └─ /agents/process → 202 + job_id
   └─ Background task con logging en Redis
   └─ GET /jobs/{job_id}/status
   ⚠️ Limitación: si el worker cae, el job se pierde
```

### Fase Industrial — Solución Robusta (3-5 días)

```
3. [R1] — Reemplazar BackgroundTasks por RQ (Redis Queue) (2 horas)
   └─ RQ Worker separado que ejecuta Orchestrator
   └─ Jobs persistentes en Redis (sobreviven a reinicios)
   └─ Reintentos automáticos configurables

4. [5] + [6] — Checkpoint por stage + resume funcional (2 horas)
   └─ Orchestrator.graba después de cada stage
   └─ Resume real desde último checkpoint exitoso

5. Validación E2E con ISSSTE BCS usando endpoint async + cola persistente
```

### Fase Optimización (después de E2E validado)

```
6. [8] — GenerationFactory (libera VRAM — ver docs/REFACTORIZACION_DE_AGENTES.md)
7. [9] — Chunking optimizado 2k tokens (reduce thrashing Ollama)
8. [11] + [12] — ForensicAuditor con rigor forense
```

### Responsabilidades sugeridas

| Día | Responsables | Entregable |
|---|---|---|
| Día 1 | Cursor | Endpoint async 202 + BackgroundTasks |
| Día 1 | Antigravity | Verificación healthcheck + timeout |
| Día 3 | Antigravity | Integración RQ Worker |
| Día 3 | Cursor | Checkpoint por stage + resume |
| Día 5 | Todos | E2E validation ISSSTE BCS |

### Criterios de aceptación por fase (Definition of Done)

#### Fase Transición (BackgroundTasks)
- `POST /agents/process` responde `202` con `job_id` en menos de 2 segundos.
- `GET /jobs/{job_id}/status` refleja estados `QUEUED -> RUNNING -> COMPLETED/FAILED`.
- La corrida E2E de ISSSTE BCS finaliza sin timeout HTTP del cliente.
- Se registra al menos un estado intermedio de progreso (`stage` y/o `pct`) antes del cierre.

#### Fase Industrial (RQ + persistencia)
- Si reinicia el proceso API, los jobs en cola no se pierden.
- Si cae un worker, el job se reintenta según política definida.
- El estado del job persiste en Redis hasta completar TTL configurado.
- La corrida E2E de ISSSTE BCS se ejecuta 2 veces consecutivas sin timeout ni pérdida de estado.

#### Fase Resumible (checkpoint real)
- El Orchestrator registra checkpoint después de cada stage crítico.
- `resume_generation=true` retoma desde el último checkpoint válido, no desde cero.
- Ante fallo simulado en mitad de pipeline, la reanudación completa el flujo sin reprocesar stages finalizados.

#### Fase Optimización (latencia)
- Reducir latencia total E2E al menos 20% sobre baseline documentado.
- Mantener calidad forense (sin pérdida de campos obligatorios ni evidencia literal).
- No incrementar tasa de `FAILED` por extracción o validación respecto al baseline.

---

## 5. Mantenimiento de Rigor Forense

### 5.1 Lo que NO cambia

- La extracción LITERAL de texto sigue siendo obligatoria
- La "Tarjeta Forense" (Ubicación + Sección + Texto Literal) es contrato obligatorio
- El Compliance Agent sigue haciendo Map-Reduce exhaustivo
- Cada bloque sigue siendo evaluado contra requisitos literales

### 5.2 Lo que MEJORA con async

| Aspecto forense | Situación actual | Con async |
|---|---|---|
| Timeout = pérdida de análisis | Si el cliente se desconecta a los 40 min, se pierde todo | El análisis corre en background; si el cliente se desconecta, el job sigue y el resultado se consulta después |
| Checkpoint por stage | Solo al final (vía agents individuales) | checkpoint después de cada zone de Compliance + cada stage del Orchestrator |
| Recuperación ante falla | Reinicio completo | Resume desde último checkpoint exitoso |
| Trazabilidad | Completa si termina | Completa incluso si hay timeout (via Forensic Traceback) |

### 5.3 Checkpoint forense mínimo viable

Para asegurar que NUNCA se pierdan datos:

```python
# Cada zone de Compliance graba su resultado inmediatamente al terminar
if settings.EXPERIENCE_LAYER_ENABLED:
    for zone_result in zone_reports:
        # ACTUALIZAR progreso en Redis para Traceback Forense
        _update_job_status(job_id, "RUNNING", {
            "stage": "compliance",
            "zone": zone_result['zone'],
            "pct": calculate_pct_by_zone(zone_result['zone'])
        })

        await self.context_manager.record_task_completion(
            session_id=session_id,
            task_name=f"zone_completed:{zone_result['zone']}",
            result={  # Datos completos, no resúmenes
                "stage": "compliance",
                "zone": zone_result['zone'],
                "status": zone_result['status'],
                "items": reduced_items,  # Los requisitos encontrados en esta zona
                "zone_metrics": zone_result.get("metrics", {}),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
```

---

## 6. Resumen Ejecutivo para el Equipo

| # | Cambio | Prioridad | Tiempo | Impacto en timeout |
|---|---|---|---|---|
| A | Timeout cliente 7200s | INMEDIATA | 5 min | Elimina timeout inmediato |
| B | Healthcheck docker | INMEDIATA | 5 min | Verificación de robustez |
| 1 | Endpoint async 202 | CRÍTICA | 2 hrs | Resuelve raíz del problema |
| 2 | Background task | CRÍTICA | (con 1) | Habilita procesamiento largo |
| 3 | GET /jobs/status | CRÍTICA | (con 1) | Visibilidad para cliente |
| 5 | Checkpoint por stage | IMPORTANTE | 1 hr | Blindaje de datos |
| 6 | Resume funcional | IMPORTANTE | 1 hr | Recuperación ante fallas |
| 8 | GenerationFactory | SEGUNDA | (ver doc refactor) | Libera VRAM |
| 9 | Chunking 2k | SEGUNDA | 30 min | Reduce tiempo LLM |
| 11 | ForensicAuditor rigor | TERCERA | (ver doc refactor) | Mejora calidad |

**Resumen de estimado:** Fase Transición ~2.5 horas. Fase Industrial ~3-5 días adicionales. Solución definitiva vía RQ con checkpoint transaccional.

---

## 7. Métricas de seguimiento recomendadas

Para evitar subjetividad durante la implementación:

- `e2e_total_duration_sec`: duración total por corrida.
- `stage_duration_sec.{analysis,compliance,economic}`: latencia por etapa.
- `job_success_rate_24h`: proporción de jobs `COMPLETED` en 24h.
- `job_retry_count`: reintentos promedio por job.
- `resume_success_rate`: porcentaje de reanudaciones exitosas.
- `forensic_quality_gate_pass_rate`: cumplimiento de contrato forense (ubicación + sección + texto literal).

---

## 8. Anexos

- **Corrida original:** `docs/corrida_tarde_issste_bcs.json`
- **Refactorización de agentes:** `docs/REFACTORIZACION_DE_AGENTES.md`
- **AGENTS_CONTEXT.md:** Contexto compartido del proyecto

---

**[REPORTE_AGENTE]**
Agente: claude
Objetivo: Dictamen técnico definitivo + propuesta de solución para timeout ISSSTE BCS
Cambios realizados: Documento de diagnóstico y solución creado en `docs/DICTAMEN_TIMEOUT_ISSSTE_BCS.md`
Validación ejecutada: Lectura de agents.py, upload.py, orchestrator.py, compliance.py, mcp_context.py
Resultado: Causa raíz confirmada — ventana HTTP síncrona insuficiente para workload de procesamiento forense. Checkpoint existe a nivel de agentes pero no entre stages del Orchestrator.
Riesgos/Pendientes: La implementación de async [1][2][3] requiere cambios en frontend para polling de estado
Siguiente paso recomendado: Implementar Día 1 (timeouts + async endpoint) para resolver definitivamente el timeout

---

**Nota de versión v1.2 (Cursor):**
- Se corrigió terminología editorial.
- Se añadieron criterios de aceptación por fase (DoD) para ejecución objetiva.
- Se agregaron métricas de seguimiento para validar mejoras de latencia y resiliencia.
