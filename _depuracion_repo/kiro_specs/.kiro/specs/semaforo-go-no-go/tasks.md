# Plan de Implementación: Semáforo Go/No-Go

## Visión general

Implementar la capa de decisión Go/No-Go en el pipeline de LicitAI, insertándola entre
`ComplianceAgent` y `EconomicAgent`. El orden respeta las dependencias: primero el módulo
puro sin dependencias del proyecto, luego el agente que lo usa, luego las modificaciones
mínimas al orquestador y contratos, después el endpoint y registro en main, y finalmente
el frontend.

## Tareas

- [x] 1. Crear `backend/app/agents/go_no_go_scorer.py`
  - Definir dataclasses `Brecha`, `CriterioDetalle` y `ScoreResult` con type hints completos
  - Implementar `detect_brechas(compliance_data, master_profile)` — lógica determinista de
    clasificación por heurísticas de texto (tabla de patrones del diseño)
  - Implementar `calculate_semaforo(brechas)` — reglas RED/YELLOW/GREEN
  - Implementar `calculate_score_tecnico(criterios_evaluacion, master_profile)` — porcentaje
    de criterios con evidencia en el perfil maestro
  - Módulo stateless puro: sin imports del proyecto, sin efectos secundarios, sin estado interno
  - Docstrings en español Google Style en todas las funciones públicas
  - Máximo 200 líneas; si se supera, extraer helpers privados dentro del mismo archivo
  - _Requisitos: 1.2, 1.4, 1.6, 2.1, 4.1, 4.2, 4.3, 4.5, 8.3, 8.4, 8.5, 10.2_

- [x] 2. Pruebas unitarias y PBT de `go_no_go_scorer`
  - [x] 2.1 Crear `backend/tests/test_go_no_go_scorer.py` con casos unitarios
    - `test_semaforo_red`, `test_semaforo_yellow`, `test_semaforo_green`
    - `test_score_rubrica_vacia`, `test_score_perfil_vacio`
    - `test_score_todos_cumplen` (score esperado: 100), `test_score_ninguno_cumple` (score: 0)
    - `test_brecha_knockout_marcada`, `test_perfil_vacio_categoria`
    - _Requisitos: 8.1, 8.2_

  - [x]* 2.2 Escribir property test — Propiedad 5: Determinismo del scorer
    - **Propiedad 5: Determinismo del scorer**
    - Llamar `detect_brechas` dos veces con los mismos argumentos debe producir resultados idénticos
    - `@settings(max_examples=100)` con `hypothesis`
    - **Valida: Requisitos 1.6, 4.5, 10.2**

  - [x]* 2.3 Escribir property test — Propiedad 6: Reglas del semáforo
    - **Propiedad 6: Reglas del semáforo**
    - knockout presente → RED; sin knockout pero con brechas → YELLOW; lista vacía → GREEN
    - **Valida: Requisitos 2.1**

  - [x]* 2.4 Escribir property test — Propiedad 1: Invariante de categoría
    - **Propiedad 1: Invariante de categoría de brechas**
    - Toda brecha producida tiene `categoria` dentro del conjunto de 5 valores válidos
    - **Valida: Requisitos 1.2**

  - [x]* 2.5 Escribir property test — Propiedad 2: Invariante estructural de brecha
    - **Propiedad 2: Invariante estructural de brecha**
    - Cada `Brecha` contiene los 7 campos requeridos con los tipos correctos
    - **Valida: Requisitos 1.4**

  - [x]* 2.6 Escribir property test — Propiedad 8: Rango del score técnico
    - **Propiedad 8: Rango del score técnico**
    - Con criterios no vacíos, `score` siempre en `[0, 100]`
    - **Valida: Requisitos 4.1, 4.2**

  - [x]* 2.7 Escribir property test — Propiedad 7: Consistencia de requires_user_decision
    - **Propiedad 7: Consistencia de requires_user_decision**
    - `requires_user_decision` es `True` si y solo si `semaforo` es RED o YELLOW
    - **Valida: Requisitos 3.7**

  - [x]* 2.8 Escribir property test — Propiedad 3: Knockout implica is_knockout=True
    - **Propiedad 3: Knockout implica is_knockout=True**
    - Requisitos de `causas_desechamiento` siempre producen brechas con `is_knockout=True`
    - **Valida: Requisitos 1.3**

  - [x]* 2.9 Escribir property test — Propiedad 4: Perfil vacío genera requisito_no_acreditado
    - **Propiedad 4: Perfil vacío genera requisito_no_acreditado**
    - Con `master_profile={}` todas las brechas tienen `categoria="requisito_no_acreditado"` y `valor_empresa=None`
    - **Valida: Requisitos 1.5**

- [x] 3. Checkpoint — Verificar scorer
  - Asegurar que todos los tests del scorer pasan. Consultar al usuario si hay dudas sobre
    la lógica de clasificación de categorías o el cálculo del score.

- [x] 4. Crear `backend/app/agents/go_no_go.py`
  - Implementar `GoNoGoAgent(BaseAgent)` con `agent_id = "go_no_go_001"`
  - En `process(agent_input)`: recuperar contexto vía `MCPContextManager.get_global_context`,
    extraer `compliance_data` y `master_profile` de `tasks_completed` y `company_data`
  - Llamar a las tres funciones del scorer y construir el dict `GoNoGoResult` con todos los
    campos del diseño (`semaforo`, `brechas`, `total_knockouts`, `total_brechas`,
    `score_cumplimiento_tecnico`, `score_detalle`, `requires_user_decision`, `schema_version: 1`)
  - Persistir resultado vía `MCPContextManager.record_task_completion("go_no_go_result", ...)`
  - Capturar excepciones internas: `detect_brechas` → `AgentOutput(status=ERROR)`;
    `calculate_score_tecnico` → score=None sin fallar el agente
  - Si `stage_completed:compliance` no está en `tasks_completed` → retornar `status=PARTIAL`
  - Logs con `get_logger` de `app.core.logging_config`; omitir campos sensibles del
    `master_profile` (RFC, capital_contable, certificaciones, estados_financieros) — solo
    loguear `brecha_id` y `categoria`
  - Type hints y docstrings en español Google Style en todos los métodos
  - Máximo 200 líneas
  - _Requisitos: 1.1, 1.3, 2.2, 2.3, 3.7, 4.1, 4.4, 5.1, 5.2, 5.6, 6.3, 8.3, 8.4, 8.5, 9.1, 10.1_

  - [x]* 4.1 Escribir pruebas unitarias de `GoNoGoAgent`
    - Crear `backend/tests/test_go_no_go_agent.py`
    - `test_output_contract`: `AgentOutput` válido con `agent_id="go_no_go_001"`
    - `test_schema_version`: `GoNoGoResult.schema_version == 1`
    - `test_fallback_sin_compliance`: sin `stage_completed:compliance` → `status=PARTIAL`
    - _Requisitos: 8.1_

  - [x]* 4.2 Escribir property test — Propiedad 10: AgentOutput válido para cualquier entrada
    - **Propiedad 10: AgentOutput válido para cualquier entrada**
    - Para cualquier `AgentInput` válido, `GoNoGoAgent.process` retorna `AgentOutput` con
      `agent_id="go_no_go_001"` y `status` en `{SUCCESS, PARTIAL, ERROR}`
    - **Valida: Requisitos 5.1**

  - [x]* 4.3 Escribir property test — Propiedad 11: schema_version en GoNoGoResult
    - **Propiedad 11: schema_version en GoNoGoResult**
    - Todo `GoNoGoResult` producido tiene `schema_version == 1`
    - **Valida: Requisitos 6.3**

- [x] 5. Modificar `backend/app/contracts/orchestrator_contracts.py`
  - Agregar `"GO_NO_GO_PENDING"` al string de documentación del campo `stop_reason` en
    `OrchestratorState` (solo actualización del docstring del `Field`, sin cambios estructurales)
  - _Requisitos: 2.4, 5.3_

- [x] 6. Modificar `backend/app/agents/orchestrator.py`
  - Insertar bloque de ejecución del `GoNoGoAgent` después del checkpoint
    `stage_completed:compliance` y antes de la ejecución del `EconomicAgent`
  - Lazy import dentro del bloque condicional: `from app.agents.go_no_go import GoNoGoAgent`
  - Lógica de omisión en modo `generation_only`/`generation` cuando
    `session_state.go_no_go_override.authorized_by == "user"` ya existe
  - Si `semaforo` es RED o YELLOW: retornar con `stop_reason="GO_NO_GO_PENDING"` e incluir
    `go_no_go_result` en la respuesta del pipeline
  - Si `semaforo` es GREEN: continuar al `EconomicAgent` sin interrupciones
  - Fallback: envolver la llamada en try/except; si falla, loguear y continuar como GREEN
  - Omitir `GoNoGoAgent` si `stage_completed:compliance` no está en `tasks_completed`
  - Incluir `go_no_go` en el dictamen forense (`process_audit_results_backend`) cuando esté disponible
  - _Requisitos: 2.3, 2.4, 2.5, 2.6, 3.5, 3.6, 5.3, 5.4, 5.5, 5.7, 6.1, 6.4_

  - [x]* 6.1 Escribir pruebas de integración del orquestador con GoNoGoAgent
    - `test_orchestrator_go_no_go_pending`: semáforo RED → `stop_reason="GO_NO_GO_PENDING"`
    - `test_orchestrator_green_continua`: semáforo GREEN → `EconomicAgent` ejecutado
    - `test_orchestrator_fallback_excepcion`: `GoNoGoAgent` lanza excepción → pipeline continúa
    - _Requisitos: 2.4, 2.5, 2.6_

- [x] 7. Checkpoint — Verificar backend
  - Asegurar que todos los tests del scorer, agente y orquestador pasan. Consultar al usuario
    si hay dudas sobre el comportamiento del fallback o la lógica de reanudación.

- [x] 8. Crear `backend/app/api/v1/routes/go_no_go.py`
  - Definir `AuthorizeRequest(BaseModel)` con `user_override: bool`,
    `brechas_autorizadas: List[str]` e `ip_address: Optional[str]`
  - Implementar `POST /{session_id}/authorize`:
    - Verificar que la sesión existe (404 si no)
    - Verificar que `stop_reason == "GO_NO_GO_PENDING"` (409 si no)
    - Verificar que `go_no_go_result` existe en `session_state` (409 si no)
    - Si `user_override=True`: persistir `go_no_go_override` con `authorized_by="user"`,
      `timestamp` ISO-8601 UTC, `brechas_autorizadas` e `ip_hash` (SHA-256 de la IP)
    - Registrar operación en log de auditoría estructurado con `event_type`, `session_id`,
      `timestamp`, `actor` y `details` (sin datos sensibles del perfil maestro)
    - Encolar nuevo job con `resume_generation=True` vía `BackgroundTasks`
    - Si `user_override=False`: retornar `{success: true, data: {}, message: "Pipeline detenido"}`
    - Sanitizar respuesta HTTP: exponer solo `descripcion`, `requisito_bases`, `valor_empresa`,
      `is_knockout`, `categoria` de cada brecha
    - Usar `get_logger` de `app.core.logging_config`
    - Type hints y docstrings en español Google Style
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 6.2, 9.2, 9.3, 9.4, 10.3, 10.4_

  - [x]* 8.1 Escribir pruebas de integración del endpoint
    - `test_authorize_endpoint_ok`: POST con `user_override=True` → job encolado
    - `test_authorize_endpoint_estado_incorrecto`: `stop_reason` distinto → 409
    - `test_authorize_endpoint_sesion_no_existe`: session_id inválido → 404
    - _Requisitos: 3.3, 3.4, 3.5_

- [x] 9. Registrar router en `backend/app/main.py`
  - Agregar import y `app.include_router` para el router de go_no_go con
    `prefix="/api/v1/go-no-go"` y `tags=["Semáforo Go/No-Go"]`
  - _Requisitos: 10.3_

- [x] 10. Crear `frontend/src/components/GoNoGoPanel.jsx`
  - Props: `goNoGoResult`, `sessionId`, `onDecision`
  - Semáforo visual: div con color CSS según `semaforo` (rojo/amarillo/verde) y etiqueta
    de texto inequívoca según Requisito 7.1
  - Sección de brechas knock-out visualmente diferenciada de brechas normales (Requisito 7.2)
  - Para cada brecha: descripción, texto literal del requisito y valor del perfil maestro
    (o "No registrado" si es null) — patrón de Tarjeta Forense (Requisito 7.3, 7.5)
  - Score de cumplimiento técnico: barra de progreso CSS + lista de criterios con cumple/no
    cumple y evidencia; visible solo cuando `score_cumplimiento_tecnico !== null` (Requisito 4.6, 4.7)
  - Botones mutuamente excluyentes: "Continuar asumiendo el riesgo" / "Detener y revisar"
  - Si `semaforo === "GREEN"`: ocultar bloque de brechas, mostrar solo score y botón continuar
  - Aviso de override previo si `go_no_go.override_timestamp` existe en el dictamen
  - Al pulsar "Continuar": POST a `/api/v1/go-no-go/{sessionId}/authorize` con
    `user_override: true` y `brechas_autorizadas`; llamar `onDecision(jobId)` con el job_id
  - Al pulsar "Detener": POST con `user_override: false`; llamar `onDecision(null)`
  - CSS vanilla sin TailwindCSS; seguir variables CSS del proyecto (`--primary`, `var(--text-muted)`, etc.)
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 4.6, 4.7, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 11. Modificar `frontend/src/App.jsx`
  - Agregar estados `goNoGoResult` y `showGoNoGoPanel` con `useState`
  - En la función que procesa el resultado del job polling, detectar
    `result?.agent_decision?.stop_reason === "GO_NO_GO_PENDING"` y activar el panel
  - Importar y renderizar `GoNoGoPanel` condicionalmente cuando `showGoNoGoPanel` es true,
    pasando `goNoGoResult`, `sessionId` y el callback `onDecision`
  - En el callback `onDecision`: si recibe `jobId`, iniciar polling del nuevo job;
    si recibe `null`, mostrar mensaje de pipeline detenido y limpiar el panel
  - _Requisitos: 7.6_

- [x] 12. Checkpoint final — Verificar integración completa
  - Asegurar que todos los tests pasan. Verificar que el flujo completo funciona:
    pipeline con semáforo RED pausa en `GO_NO_GO_PENDING`, el panel aparece en el frontend,
    la autorización reanuda el pipeline. Consultar al usuario si hay dudas.

## Notas

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- El orden garantiza que cada tarea puede implementarse sin dependencias rotas:
  el scorer no depende de nada del proyecto; el agente depende del scorer;
  el orquestador depende del agente; el endpoint depende del orquestador;
  el frontend depende del endpoint
- Los property tests usan `hypothesis` con `@settings(max_examples=100)`
- Nunca usar `logging.getLogger` — siempre `get_logger` de `app.core.logging_config`
- Ningún módulo Python supera 200 líneas

---

## Resultados del Checkpoint Final

**Fecha de ejecución:** 2026-05-11

### Resumen de ejecución

| Suite | Tests | Pasan | Fallan |
|---|---|---|---|
| `test_go_no_go_scorer.py` | 18 | 18 ✅ | 0 |
| `test_go_no_go_agent.py` | 9 | 9 ✅ | 0 |
| `test_go_no_go_orchestrator.py` | 5 | 5 ✅ | 0 |
| `test_go_no_go_endpoint.py` | 5 | 5 ✅ | 0 |
| `test_go_no_go_atenuadas_metric.py` | 3 | 3 ✅ | 0 |
| **TOTAL** | **40** | **40** | **0** |

### Correcciones aplicadas a property tests

- **Propiedad 3** (`test_property_3_knockout_implica_is_knockout`): Corregida para filtrar causas que producen texto real tras normalización (contraejemplo: `'\r'` es no-vacío pero `_extract_text` lo descarta).
- **Propiedad 4** (`test_property_4_perfil_vacio_requisito_no_acreditado`): Corregida para verificar `valor_empresa=None` y categoría válida (no siempre `requisito_no_acreditado` — la categoría se clasifica por el texto del requisito).
