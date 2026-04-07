# Roadmap: flujo tipo licitante humano (LicitAI)

**Objetivo de producto:** la app se comporta como un humano: lee bases, identifica formatos, compendia datos necesarios por entregable, genera sin rellenar con datos falsos cuando falte lo crítico, completa carpetas técnica/económica, checklist pedido vs entregado, sobres y guía de presentación — con **bases públicas/privadas heterogéneas** en México.

**Modo de trabajo acordado**

1. **Este documento** = instrucciones por hito (qué hacer, archivos, criterios de aceptación).
2. **Otra IA / desarrollador** = implementa el hito y abre PR o commit.
3. **IA validadora (Cursor)** = ejecuta pruebas indicadas, revisa logs/código, marca hito **OK / NO OK** y solo entonces se pasa al siguiente.

**Regla:** no avanzar de hito si el anterior no está **OK**.

---

## Hito R0 — Contrato de equipo y ramas

**Tareas**

- Acordar rama `feature/human-flow` (o equivalente) y que cada hito sea 1 PR pequeño.
- Documentar en README o comentario de PR el hito cubierto.

**Validación**

- Rama existe; PR referencia `ROADMAP_FLUJO_HUMANO_LICITAI.md` y el ID del hito.

---

## Hito 1 — Catálogo de empresa en Postgres (cimientos)

**Problema:** `Company.catalog` existe en modelo SQLAlchemy pero `PostgresMemoryAdapter` no lo persiste ni lo devuelve en `get_company` / `get_companies` / `save_company`.

**Instrucciones para quien implementa**

1. En `backend/app/memory/adapters/postgres_adapter.py`:
   - `save_company`: si `data` contiene `catalog`, actualizar `db_obj.catalog` (merge sensato: reemplazo completo o merge por lista según decisión documentada en 2 líneas en el PR).
   - `get_company` y `get_companies`: incluir `"catalog": c.catalog or []` en el dict retornado.
2. Si `POST /companies/` desde frontend envía `master_profile` pero no `catalog`, comportamiento explícito: no borrar catálogo existente salvo que el payload traiga clave `catalog`.

**Pruebas**

- Nuevo test en `backend/tests/` (ej. `test_postgres_company_catalog_roundtrip.py`) con `AsyncMock` **o** test de integración si hay DB de CI: crear empresa con `catalog=[{...}]`, `get_company`, assert igualdad.
- Test manual: `docker compose exec` o API: guardar empresa con catálogo, GET y ver JSON.

**Criterios de aceptación (OK)**

- `get_company` devuelve `catalog` cuando existe en BD.
- `save_company` persiste cambios de `catalog`.
- `pytest` nuevo + suite existente sin regresiones.

**Validación (IA)**

- Grep: `catalog` aparece en `save_company` y en retornos de `get_company` / `get_companies`.
- `python -m pytest backend/tests/...` pasa.

---

## Hito 2 — EconomicAgent lee catálogo real

**Instrucciones**

- Tras Hito 1, ejecutar flujo `analysis_only` con empresa que tenga `catalog` no vacío en BD y verificar en logs que `EconomicAgent` ya no parte siempre de lista vacía por bug de adaptador.
- Añadir test mock de `get_company` con `catalog` en `test_economic_agent_behavior.py` si falta cobertura.

**Criterios de aceptación**

- Test o log demuestra uso de catálogo cuando está en BD.
- Sin cambio de comportamiento cuando `catalog=[]` (sigue pudiendo haber `price_missing`).

**Validación**

- `pytest tests/test_economic_agent_behavior.py -q` OK.

---

## Hito 3 — Estado de generación: checkpoint y resume (MVP)

**Instrucciones**

1. Definir en `session.state_data` (Postgres) esquema mínimo:
   - `generation_run_id` (uuid opcional),
   - `generation_jobs`: lista `{id, type, status: pending|done|blocked|error, detail?}`,
   - `generation_cursor` (índice o id del job activo).
2. Orquestador (`orchestrator.py`): al entrar en `generation_only` con flag `resume_generation: false` (default), inicializar jobs a partir de plan fijo MVP (ej. `technical`, `formats`, `economic_writer`, `packager`, `delivery`) **sin** aún parar por documento individual.
3. Si `resume_generation: true`, **no** reinicializar jobs con `status: done`; continuar desde primer `pending`/`blocked`.
4. API: extender `ProcessBasesRequest` con campo opcional `resume_generation: bool` y documentar en OpenAPI.

**Criterios de aceptación**

- Dos llamadas seguidas con `resume_generation: true` no duplican jobs `done`.
- Estado visible en `GET` sesión o en respuesta de `process` (campo `generation_state` en respuesta recomendado para depuración).

**Pruebas**

- Test de orquestador con memoria mock: primera pasada marca `technical` done, segunda con resume no repite.

**Validación**

- Test pasa; inspección de `orchestrator.py` y schema de request.

---

## Hito 4 — Bloqueo por datos: un documento piloto

**Instrucciones**

1. Elegir **un** output (ej. primer formato administrativo generado por `FormatsAgent` o un solo archivo si es más simple).
2. Definir lista de **slots** obligatorios (ej. `domicilio_fiscal`, `representante_legal` — ajustar a realidad del generador).
3. Antes de generar ese output: si falta slot → **no** escribir archivo final (o escribir con sufijo `_INCOMPLETO` según política explícita en PR) y retornar al orquestador `waiting_for_data` con:
   - `missing_fields` enriquecido: `{ field, label, question, blocking_job_id }`,
   - persistir `pending_questions` compatible con `ChatbotRAGAgent` **o** ampliar estructura con `question_type: profile_field`.
4. Frontend: mostrar mensaje de `chatbot_message` (ya hay patrón en `App.jsx`).

**Criterios de aceptación**

- Con perfil sin el campo obligatorio: `process` devuelve `waiting_for_data` y **no** marca el job como `done`.
- Tras completar dato vía chat (flujo existente) o vía actualización de empresa + `resume_generation: true`, el job puede completarse.

**Pruebas**

- Test unitario del validador de slots.
- Test de integración con mock de memoria.

**Validación**

- Pytest + revisión de que no se usan placeholders críticos en el doc piloto.

---

## Hito 5 — Inferencia de slots desde compliance (heterogeneidad)

**Instrucciones**

1. Nuevo módulo o función pura: entrada = ítem de compliance (`id`, texto literal, tipo); salida = JSON con lista de `slot_types` del **vocabulario cerrado** (documentar lista en código).
2. Implementación: reglas por keywords + opcional LLM con `format=json` y validación contra vocabulario.
3. Cache en `session.state_data` por `req_id` para no repetir llamadas.

**Criterios de aceptación**

- Tests con 5–10 textos de ejemplo (fixtures anonimizados) con expectativas de slots.
- Si LLM devuelve tipo inválido → descartar o mapear a `unknown` + log.

**Validación**

- Tests de golden file pasan; no regresión en tiempo de proceso inaceptable (medir en log opcional).

---

## Hito 6 — Economía en generación + intake a catálogo

**Instrucciones**

1. En `generation_only`, **antes** de `EconomicWriterAgent`, ejecutar precheck (reutilizar `EconomicAgent.process` o extraer función `_map_prices`).
2. Si `waiting_for_data` por precios: poblar `pending_questions` con entradas tipadas (`question_type: economic_price`, `concepto`, `label`, etc.).
3. Extender `ChatbotRAGAgent._handle_data_intake` (o ramificación) para persistir en `company.catalog` vía `save_company` **después** de Hito 1.
4. Tras último precio, limpiar cola y permitir `resume_generation`.

**Criterios de aceptación**

- Flujo manual: `generation_only` sin análisis previo puede bloquear por precios **o** documentar que requiere `compliance_master_list` en sesión (si es dependencia, explicitar en respuesta API).

**Pruebas**

- Tests con mocks de sesión y empresa.

**Validación**

- Log Docker: `POST /chatbot/ask` tras precios; `catalog` actualizado en BD.

---

## Hito 7 — Checklist pedido vs cumplido

**Instrucciones**

1. Generar estructura `checklist` al finalizar (o incremental): cruce entre ítems compliance relevantes y archivos en `documentos_generados` + rutas en disco.
2. API `GET /api/v1/sessions/{id}/checklist` (nuevo) o campo en dictamen extendido.
3. UI mínima: tabla o lista en `Dashboard` o `DeliveryPanel`.

**Criterios de aceptación**

- Respuesta JSON estable documentada.
- Al menos cobertura de sobres y lista de paths generados.

**Validación**

- Test API con TestClient; smoke UI manual.

---

## Hito 8 — Chat “meta” (estado del sistema)

**Instrucciones**

1. Guardar en `session.state_data` último resultado agregado de `agents/process` (`status`, `orchestrator_decision`, `stop_reason`).
2. En `ChatbotRAGAgent`, si la pregunta matchea heurística o clasificador (“por qué generaste”, “qué falta”) y no hay prioridad RAG del usuario → responder con resumen del último estado **sin** inventar citas de bases.

**Criterios de aceptación**

- Test de clasificación o ejemplo en `test_chatbot_rag_behavior.py`.

**Validación**

- Log muestra modo distinto de QUERY puro; respuesta no contradice último `process`.

---

## Hito 9 — Industrialización mínima del roadmap

**Instrucciones**

- CORS restrictivo en `ENVIRONMENT=production`.
- `structlog` o formato JSON en logs con `session_id` en `agents/process`.
- Job CI: `pytest` + lint en PR.

**Criterios de aceptación**

- Pipeline verde; documentación de variables de entorno.

---

## Definición de “objetivo logrado” (cierre del roadmap)

- Catálogo y perfil **consistentes** en BD y en agentes.
- Generación **reanudable** con estado explícito.
- Al menos **un** entregable con **bloqueo real** por datos faltantes + recuperación vía chat o empresa.
- Precheck económico en generación **o** documentación clara de prerequisitos + intake a catálogo.
- Checklist **pedido vs entregado** consultable por API.
- Chat capaz de explicar **estado del último proceso** sin confundir con RAG de bases.

---

## Notas para la IA validadora

- Tras cada hito: `python -m pytest backend/tests -q` (o subconjunto indicado).
- Si el proyecto usa Docker: `docker compose restart backend` tras cambios Python sin `--reload`.
- No aprobar hito si solo hay cambios de UI sin tests cuando el hito es backend crítico (Hito 1–6).

---

*Documento vivo: actualizar fechas y estado (TODO / EN CURSO / OK) al pie de cada hito en comentarios de PR o tabla en wiki del equipo.*
