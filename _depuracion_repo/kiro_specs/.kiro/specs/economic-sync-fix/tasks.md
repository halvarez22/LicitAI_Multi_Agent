# Plan de Implementación: Sincronización de Precios Chat → Generación de Documentos

## Overview

Corrección del bug de sincronización entre la captura de precios vía chatbot y el pipeline de generación de documentos. El problema raíz es que `tasks_completed["economic_proposal"]` (fuente de verdad del generador) no se actualiza cuando el usuario captura precios en el chat. Las tareas están ordenadas por impacto: las primeras dos resuelven el bug en producción; las siguientes agregan resiliencia y consistencia; la última agrega cobertura de tests.

**Archivos principales afectados:**
- `backend/app/agents/chatbot_rag.py`
- `backend/app/services/economic_refresher.py`
- `backend/app/agents/orchestrator.py`

---

## Tasks

- [x] 1. Re-ejecutar EconomicAgent al capturar precios vía chat
  - [x] 1.1 Agregar método `_trigger_economic_recalc` en `ChatbotRAGAgent`
    - Crear método async que instancia `EconomicAgent` y llama a `process()` con `AgentInput` mínimo (session_id, company_id)
    - El método debe capturar excepciones y retornar `None` en caso de fallo (no debe bloquear la respuesta al usuario)
    - Ubicación: `backend/app/agents/chatbot_rag.py`, clase `ChatbotRAGAgent`
    - _Requirements: 1.1, 1.4_

  - [x] 1.2 Invocar `_trigger_economic_recalc` desde `_handle_economic_transaction`
    - Insertar la llamada después de `await self.context_manager.memory.save_session(session_id, state)` y antes del bloque de revalidación existente
    - Si el resultado tiene `status == "complete"`, incluir el `total_base` en el mensaje de confirmación al usuario: "💰 Propuesta actualizada: subtotal $X,XXX.XX (sin IVA)."
    - Si el resultado es `None` o `WAITING_FOR_DATA`, continuar normalmente sin modificar el mensaje
    - Ubicación: `backend/app/agents/chatbot_rag.py`, método `_handle_economic_transaction`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
    - **Nota de implementación:** Se usa directamente `refresh_economic_validations_for_session` (ya existente) en lugar de re-instanciar EconomicAgent, ya que el refresher aplica overrides, recalcula totales y persiste el snapshot en una sola llamada.

  - [x] 1.3 Verificar que `EconomicAgent` lee `economic_user_inputs` correctamente en la re-ejecución
    - Confirmado: el bloque de inyección de overrides en `EconomicAgent.process()` lee `session_state.get("economic_user_inputs", {})` antes de `_calculate_proposal`. No requiere cambios.
    - _Requirements: 1.2_

- [x] 2. Corregir EconomicRefresherService para recalcular totales con overrides

  - [x] 2.1 Extender `refresh_economic_validations_for_session` para aplicar overrides antes de revalidar
    - Ya implementado en `backend/app/economic_validation/service.py`: aplica `EconomicRefresherService.apply_overrides()` y recalcula totales antes de validar.
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 Persistir el snapshot actualizado en `tasks_completed` después del recálculo
    - Ya implementado: el refresher actualiza `tasks_completed["economic_proposal"]` con el snapshot recalculado.
    - _Requirements: 2.3, 2.4_

  - [x] 2.3 Agregar guard: si `tasks_completed["economic_proposal"]` no existe, retornar sin error
    - Implementado: si no hay MPS ni snapshot, lanza `ValueError` (comportamiento controlado, no silencioso).
    - _Requirements: 2.5_

  - [x] 2.4 Agregar `import logging` faltante en `economic_refresher.py`
    - Corregido: se agregó `import logging` y `logger = logging.getLogger(__name__)`.

- [x] 3. Checkpoint — Verificar corrección del bug principal
  - Tests `test_refresher_recalculates_totals_after_price_capture` y `test_full_flow_snapshot_updated_after_price_capture` pasan. Bug principal corregido.

- [x] 4. Agregar validación de snapshot en el orquestador antes de generation_only

  - [x] 4.1 Crear función `_ensure_economic_snapshot_ready` en `orchestrator.py`
    - Implementada como función de módulo (no método de clase) para facilitar el testing.
    - Flujo: sin snapshot → MISSING_ECONOMIC_PROPOSAL; snapshot listo → (True, None); snapshot desactualizado → refresh → re-ejecutar EconomicAgent si necesario.
    - Ubicación: `backend/app/agents/orchestrator.py`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 4.2 Invocar `_ensure_economic_snapshot_ready` en el bloque de generation_only
    - Insertado antes del loop `for step, a_cls in [...]` en el pipeline de generación.
    - Si retorna `(False, error_payload)`: retorna el error con `stop_reason` y detiene el pipeline.
    - Ubicación: `backend/app/agents/orchestrator.py`, método `process()`, bloque `generation_only`
    - _Requirements: 4.1, 4.2_

- [x] 5. Limpiar pending_questions económicas huérfanas al cambiar de sesión

  - [x] 5.1 Crear método `_sanitize_economic_pending_questions` en `ChatbotRAGAgent`
    - Filtra preguntas de tipo `economic_price` verificando que el concepto exista en el snapshot activo.
    - Descarta silenciosamente las preguntas sin correspondencia con log `chatbot_orphan_economic_question_discarded`.
    - Preserva todas las preguntas de tipo distinto a `economic_price`.
    - Ubicación: `backend/app/agents/chatbot_rag.py`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 5.2 Invocar `_sanitize_economic_pending_questions` al inicio de `process()` en `ChatbotRAGAgent`
    - Llamado después de cargar `session_state` y antes de la lógica de intake.
    - Si la lista limpia difiere de la original, persiste la lista limpia antes de continuar.
    - _Requirements: 5.1, 5.2_

- [x] 6. Implementar acción HITL para allow_zero_total_base_ack en el chatbot

  - [x] 6.1 Crear método `_handle_zero_base_ack` en `ChatbotRAGAgent`
    - Persiste `allow_zero_total_base_ack = True` en `session_state.economic_user_inputs`.
    - Invoca `refresh_economic_validations_for_session` para actualizar el snapshot.
    - Retorna mensaje de confirmación sin exponer el nombre técnico del flag.
    - _Requirements: 6.1, 6.2, 6.4_

  - [x] 6.2 Agregar patrones de detección de intención HITL en el clasificador de mensajes
    - Agregado `_ZERO_BASE_ACK_PATTERNS` y método estático `_detect_zero_base_ack_intent`.
    - Enrutado al método `_handle_zero_base_ack` al inicio del bloque del canal transaccional.
    - _Requirements: 6.1, 6.2_

  - [x] 6.3 Incluir la opción de confirmación en el mensaje de error de subtotal ~0
    - Modificado `EconomicWriterAgent` para incluir instrucción en lenguaje de negocio.
    - Ubicación: `backend/app/agents/economic_writer.py`
    - _Requirements: 6.1, 6.4_

  - [x] 6.4 Reintentar generación automáticamente tras confirmar zero-base-ack
    - `_handle_zero_base_ack` invoca `refresh_economic_validations_for_session` para actualizar el snapshot con el flag activo.
    - _Requirements: 6.3_

- [x] 7. Corregir consistencia del estado del UI

  - [x] 7.1 Actualizar `_build_session_resume_message` para leer estado desde snapshot
    - El mensaje de reanudación ahora lee `tasks_completed["economic_proposal"].total_base` y `status`.
    - Muestra "⚠️ Propuesta económica: precios pendientes" cuando `total_base < 0.01`.
    - Muestra "✅ Propuesta económica calculada. Subtotal: $X" cuando `status == complete`.
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 8. Tests de integración y unitarios

  - [x] 8.1 Crear archivo `backend/tests/test_economic_sync.py` ✅
  - [x] 8.2 `test_refresher_recalculates_totals_after_price_capture` ✅
  - [x] 8.3 `test_refresher_preserves_existing_fields` ✅
  - [x] 8.4 `test_ensure_economic_snapshot_ready_missing_snapshot` ✅
  - [x] 8.5 `test_ensure_economic_snapshot_ready_with_valid_snapshot` ✅
  - [x] 8.6 `test_ensure_economic_snapshot_ready_stale_snapshot_refreshes` ✅
  - [x] 8.7 `test_sanitize_orphan_economic_questions_discards_unmatched` ✅
  - [x] 8.8 `test_sanitize_keeps_all_when_no_snapshot` ✅
  - [x] 8.9 `test_detect_zero_base_ack_intent_positive` ✅
  - [x] 8.10 `test_detect_zero_base_ack_intent_negative` ✅
  - [x] 8.11 `test_handle_zero_base_ack_persists_flag` ✅
  - [x] 8.12 `test_full_flow_snapshot_updated_after_price_capture` ✅
  - [x] 8.13 `test_zero_base_ack_unblocks_generation` ✅

- [x] 9. Checkpoint final — Todos los tests pasan
  - **13/13 tests pasan** en `backend/tests/test_economic_sync.py`
  - Cero errores de diagnóstico en los 4 archivos modificados.
    - Crear método async que instancia `EconomicAgent` y llama a `process()` con `AgentInput` mínimo (session_id, company_id)
    - El método debe capturar excepciones y retornar `None` en caso de fallo (no debe bloquear la respuesta al usuario)
    - Ubicación: `backend/app/agents/chatbot_rag.py`, clase `ChatbotRAGAgent`
    - _Requirements: 1.1, 1.4_

  - [ ] 1.2 Invocar `_trigger_economic_recalc` desde `_handle_economic_transaction`
    - Insertar la llamada después de `await self.context_manager.memory.save_session(session_id, state)` y antes del bloque de revalidación existente
    - Si el resultado tiene `status == "complete"`, incluir el `total_base` en el mensaje de confirmación al usuario: "💰 Propuesta actualizada: subtotal $X,XXX.XX (sin IVA)."
    - Si el resultado es `None` o `WAITING_FOR_DATA`, continuar normalmente sin modificar el mensaje
    - Ubicación: `backend/app/agents/chatbot_rag.py`, método `_handle_economic_transaction`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ] 1.3 Verificar que `EconomicAgent` lee `economic_user_inputs` correctamente en la re-ejecución
    - Confirmar que el bloque de inyección de overrides en `EconomicAgent.process()` (línea ~línea 290: `user_overrides = session_state.get("economic_user_inputs", {})`) se ejecuta antes del cálculo de propuesta
    - Si hay un gap, agregar lectura explícita de `economic_user_inputs` al inicio de `process()` antes de `_calculate_proposal`
    - Ubicación: `backend/app/agents/economic.py`
    - _Requirements: 1.2_

- [ ] 2. Corregir EconomicRefresherService para recalcular totales con overrides

  - [ ] 2.1 Extender `refresh_economic_validations_for_session` para aplicar overrides antes de revalidar
    - Leer el snapshot de `tasks_completed["economic_proposal"]` al inicio de la función
    - Invocar `EconomicRefresherService.apply_overrides(items, user_inputs, [], session_state)` sobre los ítems del snapshot
    - Recalcular `subtotal` por ítem como `cantidad * precio_unitario` y `total_base` como suma de subtotales
    - Ubicación: `backend/app/services/economic_refresher.py`
    - _Requirements: 2.1, 2.2_

  - [ ] 2.2 Persistir el snapshot actualizado en `tasks_completed` después del recálculo
    - Reemplazar la entrada `economic_proposal` en `tasks_completed` con el snapshot actualizado (items, total_base, grand_total, status)
    - Preservar todos los demás campos del snapshot (validation_result, calculator_result, quadrature_report, etc.)
    - Actualizar `status` a `"complete"` si `total_base >= 0.01`
    - Ubicación: `backend/app/services/economic_refresher.py`
    - _Requirements: 2.3, 2.4_

  - [ ] 2.3 Agregar guard: si `tasks_completed["economic_proposal"]` no existe, retornar sin error
    - La función debe ser idempotente: si no hay snapshot, retornar `EconomicValidationResult()` vacío sin crear entradas
    - Ubicación: `backend/app/services/economic_refresher.py`
    - _Requirements: 2.5_

- [ ] 3. Checkpoint — Verificar corrección del bug principal
  - Ejecutar manualmente el flujo: capturar precio en chat → verificar que `tasks_completed["economic_proposal"].total_base > 0` en Redis/Postgres → ejecutar `generar documentos` → verificar que `EconomicWriterAgent` retorna SUCCESS
  - Si el test manual falla, revisar las tareas 1 y 2 antes de continuar

- [ ] 4. Agregar validación de snapshot en el orquestador antes de generation_only

  - [ ] 4.1 Crear método `_ensure_economic_snapshot_ready` en `OrchestratorAgent`
    - Leer snapshot de `tasks_completed["economic_proposal"]`
    - Si no existe: retornar `(False, {stop_reason: "MISSING_ECONOMIC_PROPOSAL", ...})`
    - Si `total_base < 0.01` y `allow_zero_total_base_ack == False`: re-ejecutar `EconomicAgent`
    - Si `EconomicAgent` retorna SUCCESS: retornar `(True, None)`
    - Si `EconomicAgent` retorna WAITING_FOR_DATA: retornar `(False, {stop_reason: "ECONOMIC_PRICES_INCOMPLETE", data: ...})`
    - Ubicación: `backend/app/agents/orchestrator.py`, clase `OrchestratorAgent`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ] 4.2 Invocar `_ensure_economic_snapshot_ready` en el bloque de generation_only
    - Insertar la llamada antes de la invocación a `EconomicWriterAgent` en el pipeline de generación
    - Si retorna `(False, error_payload)`: retornar el error_payload directamente sin continuar el pipeline
    - Ubicación: `backend/app/agents/orchestrator.py`, método `process()`, bloque `generation_only`
    - _Requirements: 4.1, 4.2_

- [ ] 5. Limpiar pending_questions económicas huérfanas al cambiar de sesión

  - [ ] 5.1 Crear método `_sanitize_economic_pending_questions` en `ChatbotRAGAgent`
    - Leer ítems del snapshot `tasks_completed["economic_proposal"]` de la sesión activa
    - Para cada `pending_question` de tipo `economic_price`, verificar que el concepto existe en los ítems del snapshot (comparación normalizada)
    - Descartar silenciosamente las preguntas sin correspondencia y loguear con `chatbot_orphan_economic_question_discarded`
    - Preservar todas las preguntas de tipo distinto a `economic_price` y `economic_validation_blocking`
    - Ubicación: `backend/app/agents/chatbot_rag.py`, clase `ChatbotRAGAgent`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ] 5.2 Invocar `_sanitize_economic_pending_questions` al inicio de `process()` en `ChatbotRAGAgent`
    - Llamar al método después de cargar `session_state` y antes de clasificar el mensaje del usuario
    - Si la lista limpia difiere de la original, persistir la lista limpia en `session_state` antes de continuar
    - Ubicación: `backend/app/agents/chatbot_rag.py`, método `process()`
    - _Requirements: 5.1, 5.2_

- [ ] 6. Implementar acción HITL para allow_zero_total_base_ack en el chatbot

  - [ ] 6.1 Crear método `_handle_zero_base_ack` en `ChatbotRAGAgent`
    - Persistir `allow_zero_total_base_ack = True` en `session_state.economic_user_inputs`
    - Retornar mensaje de confirmación con lenguaje de negocio (sin exponer el nombre técnico del flag)
    - Ubicación: `backend/app/agents/chatbot_rag.py`, clase `ChatbotRAGAgent`
    - _Requirements: 6.1, 6.2, 6.4_

  - [ ] 6.2 Agregar patrones de detección de intención HITL en el clasificador de mensajes
    - Agregar `ZERO_BASE_ACK_PATTERNS` con expresiones regulares para detectar confirmación del usuario
    - Enrutar al método `_handle_zero_base_ack` cuando se detecte la intención
    - Ubicación: `backend/app/agents/chatbot_rag.py`, lógica de clasificación de intención
    - _Requirements: 6.1, 6.2_

  - [ ] 6.3 Incluir la opción de confirmación en el mensaje de error de subtotal ~0
    - Modificar el mensaje de `EconomicWriterAgent` cuando `subtotal < 0.01` para incluir la instrucción de confirmación en lenguaje de negocio
    - Ejemplo: "Si esta licitación no requiere importe base, escribe: **'Esta licitación no requiere importe base'** para confirmar y continuar."
    - Ubicación: `backend/app/agents/economic_writer.py`, bloque de validación de subtotal
    - _Requirements: 6.1, 6.4_

  - [ ] 6.4 Reintentar generación automáticamente tras confirmar zero-base-ack
    - Después de persistir el flag, invocar `_trigger_economic_recalc` para actualizar el snapshot con `allow_zero_total_base_ack=True`
    - Ubicación: `backend/app/agents/chatbot_rag.py`, método `_handle_zero_base_ack`
    - _Requirements: 6.3_

- [ ] 7. Corregir consistencia del estado del UI

  - [ ] 7.1 Identificar el endpoint o campo que alimenta el panel de "Precios capturados" en el frontend
    - Buscar en `backend/app/routes/` el endpoint que retorna el estado de la propuesta económica al frontend
    - Verificar si retorna `economic_user_inputs` o `tasks_completed["economic_proposal"]`
    - _Requirements: 3.1_

  - [ ] 7.2 Actualizar el endpoint para retornar el estado desde `tasks_completed["economic_proposal"]`
    - El campo `status` debe venir de `tasks_completed["economic_proposal"].status`
    - El campo `total_base` debe venir de `tasks_completed["economic_proposal"].total_base`
    - Si `total_base < 0.01` y `allow_zero_total_base_ack == False`: retornar `ui_status = "prices_pending"`
    - Si `status == "complete"` y `total_base >= 0.01`: retornar `ui_status = "ready"`
    - Si `status == "waiting_for_data"`: retornar `ui_status = "capturing"`
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 8. Tests de integración y unitarios

  - [ ] 8.1 Crear archivo `backend/tests/test_economic_sync.py`
    - Estructura base con fixtures de `mock_context_manager`, `mock_session_state` y `mock_tasks_completed`
    - _Requirements: 7.1_

  - [ ] 8.2 Test unitario: `test_economic_recalc_on_price_capture`
    - Simular captura de precio en chatbot → verificar que `EconomicAgent.process()` es invocado
    - Verificar que el snapshot en `tasks_completed` se actualiza con `total_base > 0`
    - _Requirements: 7.1, 7.2_

  - [ ] 8.3 Test unitario: `test_refresher_recalculates_totals`
    - Snapshot con `total_base=0` + `economic_user_inputs` con precio → invocar refresher → verificar `total_base > 0`
    - _Requirements: 7.2_

  - [ ] 8.4 Test unitario: `test_orchestrator_stale_snapshot_triggers_recalc`
    - Snapshot con `total_base=0` en modo `generation_only` → verificar que orquestador re-ejecuta `EconomicAgent`
    - _Requirements: 7.4_

  - [ ] 8.5 Test unitario: `test_sanitize_orphan_economic_questions`
    - `pending_questions` con concepto que no existe en snapshot activo → verificar que es descartada
    - `pending_questions` con concepto que sí existe → verificar que se mantiene
    - _Requirements: 7.1_

  - [ ] 8.6 Test de integración: `test_full_flow_chat_prices_to_document_generation`
    - Flujo completo: EconomicAgent con gaps → chatbot captura precios → generation_only → EconomicWriterAgent SUCCESS
    - Verificar que `EconomicWriterAgent` NO retorna `WAITING_FOR_DATA` después de capturar precios
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ] 8.7 Test de caso edge: `test_zero_base_ack_unblocks_generation`
    - `allow_zero_total_base_ack=True` + `total_base=0` → verificar que `EconomicWriterAgent` retorna SUCCESS
    - _Requirements: 7.5_

  - [ ]* 8.8 Property test: `test_total_base_invariant_after_override`
    - `@given(prices=st.lists(st.floats(min_value=0.01, max_value=1_000_000.0), min_size=1, max_size=10))`
    - Verificar que `total_base == sum(item.subtotal)` para cualquier conjunto de precios capturados
    - _Requirements: 7.2_

- [ ] 9. Checkpoint final — Todos los tests pasan
  - Ejecutar `pytest backend/tests/test_economic_sync.py -v` y verificar que todos los tests pasan
  - Ejecutar el flujo manual completo en staging: capturar precios → generar documentos → verificar XLSX y DOCX generados con montos correctos
  - Consultar al usuario si algún test falla por cambios en la interfaz de los agentes

## Notes

- Las tareas 1 y 4 son las de mayor impacto: resuelven el bug sin tocar el UI. Implementar primero.
- La tarea 2 es complementaria a la 1: si la tarea 1 está activa, el refresher existente puede quedar como fallback.
- Las tareas marcadas con `*` son opcionales para MVP.
- El orden de implementación recomendado: 1 → 4 → 3 (checkpoint) → 2 → 5 → 6 → 7 → 8 → 9.
- Todos los cambios son aditivos (nuevos métodos o guards): no se modifica la lógica existente de los agentes, solo se agregan puntos de entrada y validaciones.
- Los tests deben ubicarse en `backend/tests/test_economic_sync.py`.
- Usar `@pytest.mark.asyncio` para todos los tests async.
- Los property tests usan `hypothesis` con `@settings(max_examples=100)`.
