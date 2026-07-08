# Plan de Implementación: Recolección Inteligente de Datos vía Chatbot

## Overview

Extender `ChatbotRAGAgent` con recálculo de semáforo tras cada guardado, añadir los métodos `_recalculate_semaforo` y `_build_semaforo_change_msg`, exponer `go_no_go_result` en la respuesta del endpoint `/chatbot/ask`, y cubrir las 10 propiedades de corrección con tests de Hypothesis.

## Tasks

- [x] 1. Añadir métodos de recálculo de semáforo a `ChatbotRAGAgent`
  - Implementar `_recalculate_semaforo(session_id, company_id)` en `backend/app/agents/chatbot_rag.py`
    - Instanciar `GoNoGoAgent` con `recalculate_only=True` (o equivalente según contrato actual)
    - Persistir el resultado en `session_state["go_no_go_result"]` vía `context_manager.memory.save_session`
    - Capturar excepciones y registrar con `logger.error`; retornar `None` en caso de fallo
  - Implementar `_build_semaforo_change_msg(prev, new)` como método estático
    - Retornar cadena vacía si `prev == new` o alguno es `None`
    - Usar iconos `🔴 🟡 🟢` para los estados RED / YELLOW / GREEN
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ]* 1.1 Property test — Property 5: Recálculo del semáforo tras cada guardado
    - **Property 5: Recálculo del semáforo tras cada guardado**
    - **Validates: Requirements 6.1, 6.2**
    - Usar `@given` con `session_id` y `company_id` arbitrarios; mockear `GoNoGoAgent.process`
    - Verificar que `GoNoGoAgent.process` es invocado y el resultado queda en `session_state["go_no_go_result"]`

  - [ ]* 1.2 Property test — Property 6: Notificación de cambio de estado del semáforo
    - **Property 6: Notificación de cambio de estado del semáforo**
    - **Validates: Requirements 6.3**
    - `@given(prev=st.sampled_from(["RED","YELLOW","GREEN"]), new=st.sampled_from(["RED","YELLOW","GREEN"]))`
    - Verificar que cuando `prev != new` la cadena retornada contiene ambos estados; cuando `prev == new` retorna `""`

- [x] 2. Integrar recálculo de semáforo en `_handle_data_intake`
  - En `backend/app/agents/chatbot_rag.py`, dentro de `_handle_data_intake`, tras la llamada exitosa a `_save_field_to_company` o `_save_price_to_catalog`:
    - Leer `prev_semaforo` desde `session_state.get("go_no_go_result", {}).get("semaforo")`
    - Invocar `await self._recalculate_semaforo(session_id, company_id)`
    - Construir `semaforo_change_msg` con `_build_semaforo_change_msg`
    - Incluir `semaforo_change_msg` en la respuesta `resp` (entre confirmación y siguiente pregunta)
  - _Requirements: 6.1, 6.2, 6.3, 3.3_

  - [ ]* 2.1 Unit test — Flujo DATA_INTAKE con recálculo exitoso
    - Verificar que la respuesta incluye confirmación del campo guardado + mensaje de cambio de semáforo
    - Mockear `_save_field_to_company` → `True`, `_recalculate_semaforo` → `{"semaforo": "GREEN"}`
    - _Requirements: 3.3, 6.3_

  - [ ]* 2.2 Unit test — Flujo DATA_INTAKE cuando recálculo falla
    - Verificar que el flujo conversacional continúa y no lanza excepción al usuario
    - Mockear `_recalculate_semaforo` → `None`
    - _Requirements: 6.4_

- [x] 3. Extender respuesta del endpoint `/chatbot/ask` con `go_no_go_result`
  - Localizar el handler del endpoint en `backend/app/api/v1/routes/` (archivo de rutas del chatbot)
  - Tras obtener `agent_output`, leer `session_state` desde `memory.get_session(session_id)`
  - Si `session_state.get("go_no_go_result")` existe, añadirlo al dict de respuesta como `"go_no_go_result"`
  - _Requirements: 6.2, 8.4_

  - [ ]* 3.1 Unit test — Endpoint incluye `go_no_go_result` cuando está en session_state
    - Verificar que la respuesta JSON contiene la clave `go_no_go_result` con el valor correcto
    - _Requirements: 6.2_

- [x] 4. Checkpoint — Verificar recálculo de semáforo end-to-end
  - Asegurar que todos los tests de las tareas 1–3 pasan
  - Verificar manualmente (o con test de integración) que tras guardar un dato el `session_state["go_no_go_result"]` se actualiza correctamente
  - Preguntar al usuario si hay dudas antes de continuar

- [ ] 5. Implementar y cubrir propiedades de corrección del flujo conversacional
  - [ ] 5.1 Property test — Property 1: Inicio proactivo con preguntas pendientes
    - **Property 1: Inicio proactivo con preguntas pendientes**
    - **Validates: Requirements 1.1, 1.3**
    - `@given(pending=st.lists(pending_question_strategy(), min_size=1), greeting=st.sampled_from(["hola","buenos días","hey","qué tal"]))`
    - Mockear `context_manager.memory.get_session` → `{"pending_questions": pending, "current_question_index": 0}`
    - Verificar que `response.data["respuesta"]` contiene `pending[0]["question"]`

  - [ ] 5.2 Property test — Property 2: Formulación completa (pregunta + hint)
    - **Property 2: Formulación completa de preguntas (pregunta + hint)**
    - **Validates: Requirements 2.1, 2.2**
    - `@given(q=pending_question_strategy())` donde la estrategia genera objetos con `question` y `document_hint` arbitrarios
    - Verificar que la respuesta contiene tanto `q["question"]` como `q["document_hint"]`

  - [ ] 5.3 Property test — Property 3: Preservación del master_profile al actualizar un campo
    - **Property 3: Preservación del master_profile al actualizar un campo**
    - **Validates: Requirements 5.2**
    - `@given(profile=st.dictionaries(st.text(min_size=1), st.text(min_size=1), min_size=1, max_size=10), new_field=st.text(min_size=1), new_value=st.text(min_size=1))`
    - Mockear `get_company` → `{"master_profile": profile}` y capturar el argumento de `save_company`
    - Verificar que todos los campos originales de `profile` están presentes en el perfil guardado

  - [ ] 5.4 Property test — Property 4: Avance secuencial del índice tras guardado exitoso
    - **Property 4: Avance secuencial del índice tras guardado exitoso**
    - **Validates: Requirements 7.1, 2.3**
    - `@given(pending=st.lists(pending_question_strategy(), min_size=2, max_size=10), idx=st.integers(min_value=0))`
    - Filtrar `idx < len(pending)`; mockear guardado exitoso
    - Verificar que `session_state["current_question_index"] == idx + 1` y la respuesta contiene `pending[idx+1]["question"]` (o mensaje de completitud si `idx+1 == len(pending)`)

  - [ ] 5.5 Property test — Property 7: Filtrado de documentos de bases/convocatoria
    - **Property 7: Filtrado de documentos de bases/convocatoria**
    - **Validates: Requirements 4.4**
    - `@given(filename=st.one_of(st.from_regex(r"(bases|convocatoria|pliego|licitacion).*\\.pdf", fullmatch=True), st.from_regex(r"[a-z]{3,20}\\.pdf", fullmatch=True)))`
    - Verificar que `DataGapAgent._filename_looks_like_bases(filename)` retorna `True` para nombres con keywords y `False` para los demás

  - [ ] 5.6 Property test — Property 8: Listado completo de pendientes ante intención de aclaración
    - **Property 8: Listado completo de pendientes ante intención de aclaración**
    - **Validates: Requirements 2.4**
    - `@given(pending=st.lists(pending_question_strategy(), min_size=1, max_size=8))`
    - Usar mensajes que activen `_evaluate_clarification_intent` (ej: "qué falta", "qué datos")
    - Verificar que la respuesta contiene el `label` de cada pregunta en `pending`

  - [ ] 5.7 Property test — Property 9: Persistencia de precios en catálogo (no en master_profile)
    - **Property 9: Persistencia de precios en catálogo (no en master_profile)**
    - **Validates: Requirements 3.6**
    - `@given(price=st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False))`
    - Mockear `get_company` → empresa con `master_profile` y `catalog` existentes
    - Verificar que el precio queda en `company["catalog"]` y `company["master_profile"]` no fue modificado

  - [ ] 5.8 Property test — Property 10: Perfil fresco desde BD (no desde frontend)
    - **Property 10: Perfil fresco desde BD (no desde frontend)**
    - **Validates: Requirements 5.4**
    - `@given(db_profile=st.dictionaries(...), stale_profile=st.dictionaries(...))`
    - Mockear `get_company` → `{"master_profile": db_profile}` y pasar `stale_profile` en `agent_input.company_data`
    - Verificar que `DataGapAgent` evalúa brechas usando `db_profile` y no `stale_profile`

- [ ] 6. Implementar tests unitarios de edge cases del flujo conversacional
  - [ ] 6.1 Unit tests — Clasificación de mensajes
    - Verificar QUERY vs DATA_INTAKE vs META para mensajes representativos
    - Cubrir heurística rápida (señales de datos, precio numérico) y fallback LLM
    - _Requirements: 8.1_

  - [ ] 6.2 Unit tests — Manejo de `AMBIGUO` en extracción de valor
    - Verificar que cuando el LLM retorna `AMBIGUO` el índice no avanza y se solicita reformulación
    - _Requirements: 3.2_

  - [ ] 6.3 Unit tests — Fallo de persistencia (`save_company` lanza excepción)
    - Verificar que el chatbot notifica al usuario y no avanza el índice
    - _Requirements: 3.5_

  - [ ] 6.4 Unit tests — `company_id` ausente
    - Verificar que el chatbot solicita seleccionar empresa y no intenta guardar datos
    - _Requirements: 5.5_

  - [ ] 6.5 Unit tests — Finalización del flujo (último dato guardado)
    - Verificar que `pending_questions` y `current_question_index` se limpian en `session_state`
    - Verificar que la respuesta contiene el mensaje de completitud
    - _Requirements: 7.2, 7.3_

- [ ] 7. Checkpoint final — Todos los tests pasan
  - Ejecutar `pytest backend/tests/ -k "chatbot_data_collection" --tb=short`
  - Asegurar que todos los property tests y unit tests pasan sin errores
  - Preguntar al usuario si hay dudas antes de cerrar la feature

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Los property tests usan `hypothesis` (Python) con `@settings(max_examples=100)` mínimo
- Cada property test debe incluir el tag `# Feature: chatbot-data-collection, Property N: descripción`
- El recálculo del semáforo nunca debe bloquear el flujo conversacional (principio de resiliencia)
- `DataGapAgent` no requiere cambios de contrato; solo se añaden tests sobre métodos existentes
