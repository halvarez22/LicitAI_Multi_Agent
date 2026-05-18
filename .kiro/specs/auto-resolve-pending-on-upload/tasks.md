# Plan de Implementación: Auto-Resolve Pending on Upload

## Visión General

Robustece y formaliza el `AutoResolveHook` (`_sync_pending_after_analysis`) en `backend/app/api/v1/routes/upload.py` para cubrir todos los casos de borde definidos en el diseño, añadir trazabilidad con `correlation_id` y `timeout`, actualizar el endpoint `process_document` con los mensajes contextuales correctos y cubrir el comportamiento con pruebas unitarias y de propiedades.

El código base ya existe y cubre el camino feliz. Las tareas siguen el orden del Migration Plan del diseño: primero el contrato del hook, luego la lógica de avance de cola, luego el endpoint, y finalmente las pruebas.

---

## Tareas

- [x] 1. Definir el tipo `AutoResolveResult` y actualizar la firma del hook
  - Añadir `AutoResolveResult` como `TypedDict` en `upload.py` con los campos: `resolved_current_pending`, `resolved_field`, `resolved_value`, `next_pending_label`, `next_pending_question`, `reason`.
  - Actualizar la firma de `_sync_pending_after_analysis` para aceptar `correlation_id: str = ""` y `timeout_seconds: float = 30.0` como parámetros keyword-only.
  - Actualizar el tipo de retorno de la función a `AutoResolveResult`.
  - _Requisitos: 1.4, 3.1, 7.3_

- [x] 2. Robustecimiento de los retornos tempranos del hook
  - [x] 2.1 Verificar y completar los retornos tempranos existentes
    - Confirmar que `missing_company_id` cubre `None`, `""` y strings de solo espacios (`.strip()`).
    - Confirmar que `no_pending_questions` cubre lista vacía y `None`.
    - Confirmar que `current_pending_not_profile` cubre cualquier `type` distinto de `"profile"` (incluyendo `"economic_price"`).
    - Confirmar que `missing_field_key` cubre `field` vacío o nulo.
    - En todos los retornos tempranos, asegurar que `next_pending_label` y `next_pending_question` se rellenan con el label/question del pendiente activo antes de retornar (para que el endpoint pueda construir el mensaje del caso 3).
    - _Requisitos: 1.4, 2.1, 2.2, 2.3, 2.4, 8.4_

  - [ ]* 2.2 Escribir pruebas unitarias para retornos tempranos
    - Crear `backend/tests/unit/test_auto_resolve_hook.py`.
    - `test_missing_company_id_none`: `company_id=None` → `reason="missing_company_id"`, sin I/O.
    - `test_missing_company_id_empty`: `company_id=""` → `reason="missing_company_id"`, sin I/O.
    - `test_no_pending_returns_early`: lista vacía → `reason="no_pending_questions"`, sin invocar `DataGapAgent`.
    - `test_non_profile_type_skipped`: `type="economic_price"` → `reason="current_pending_not_profile"`.
    - `test_empty_field_key_skipped`: `field=""` → `reason="missing_field_key"`.
    - _Requisitos: 1.4, 2.1, 2.2, 2.3_

- [x] 3. Añadir timeout y manejo de errores de persistencia al hook
  - [x] 3.1 Envolver la llamada a `DataGapAgent` con `asyncio.wait_for`
    - Importar `asyncio` si no está importado.
    - Envolver `dg.try_extract_field_from_sources(...)` con `asyncio.wait_for(..., timeout=timeout_seconds)`.
    - Capturar `asyncio.TimeoutError` y retornar `reason="timeout"`.
    - Propagar `correlation_id` a `try_extract_field_from_sources`.
    - _Requisitos: 3.1, 7.3_

  - [x] 3.2 Añadir manejo de error en la persistencia de `master_profile`
    - Envolver `memory.save_company(company_id, company)` en `try/except`.
    - Si falla, retornar `reason="persistence_error"` sin avanzar el índice ni modificar `session_state`.
    - _Requisitos: 4.4_

  - [ ]* 3.3 Escribir pruebas unitarias para timeout y errores de persistencia
    - `test_timeout_returns_gracefully`: mock de `DataGapAgent` que tarda más de `timeout_seconds` → `reason="timeout"`, HTTP 200.
    - `test_persistence_error_no_session_advance`: mock de `memory.save_company` que lanza excepción → `reason="persistence_error"`, `session_state` sin cambios.
    - _Requisitos: 4.4, 7.3_

- [x] 4. Actualizar la lógica de avance de cola para usar estado fresco
  - Reemplazar el uso de `session_state` (leído al inicio del hook) por una segunda lectura atómica: `fresh_s = await memory.get_session(session_id) or {}` justo antes de modificar la cola.
  - Usar `fresh_s` para calcular `fresh_pending`, `safe_idx`, `new_pending` y `new_idx`.
  - Guardar `fresh_s` (no `session_state`) con `memory.save_session`.
  - Añadir log de auditoría: `logger.info("[AutoResolve] ✅ Resuelto '%s' = '%s' para sesión %s", field_key, str(extracted)[:40], session_id)`.
  - _Requisitos: 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 8.2, 8.3, 8.5_

  - [ ]* 4.1 Escribir pruebas unitarias para avance de cola y log de auditoría
    - `test_invalid_value_not_persisted`: valor que no pasa `_is_data_valid` → `master_profile` sin cambios, `session_state` sin cambios.
    - `test_queue_advance_removes_resolved_item`: tras resolución, `pending_questions` tiene `N-1` elementos.
    - `test_queue_advance_empty_after_last`: tras resolver el último pendiente, `pending_questions=[]` y `current_question_index=0`.
    - `test_audit_log_on_success`: log contiene `[AutoResolve] ✅` con `field_key` y `session_id`.
    - _Requisitos: 3.2, 3.3, 4.3, 5.1, 5.2, 8.5_

- [x] 5. Checkpoint — Verificar que el hook pasa todas las pruebas unitarias
  - Asegurar que todas las pruebas unitarias en `test_auto_resolve_hook.py` pasan. Consultar al usuario si surgen dudas.

- [x] 6. Actualizar el endpoint `process_document` con mensajes contextuales y captura de excepción
  - [x] 6.1 Añadir captura de excepción no controlada alrededor de la llamada al hook
    - Envolver `await _sync_pending_after_analysis(...)` en `try/except Exception as exc`.
    - En el `except`: loguear con `logger.warning("[AutoResolve] ⚠️ Excepción no controlada en hook: %s", exc, exc_info=True)` y asignar un `sync` con `resolved_current_pending=False` y `reason="hook_exception"`.
    - _Requisitos: 7.1, 7.2_

  - [x] 6.2 Actualizar los mensajes de respuesta para incluir `filename` y `field_label`
    - En el path `ANALYZED` (sin `force`): actualizar el mensaje del caso resuelto para incluir `filename` (tomado de `doc_data["content"]["filename"]`).
    - En el path de nueva indexación: los mensajes ya incluyen `filename`; verificar que el formato coincide exactamente con el diseño (casos 1, 2 y 3).
    - Caso 1 (resuelto con siguiente): `f"He revisado el archivo **{filename}** y ya pude extraer **{sync.get('resolved_field')}**. ¡Listo! Ahora, para seguir avanzando, necesito: **{nxt}**."`.
    - Caso 2 (resuelto sin más pendientes): `f"He revisado el archivo **{filename}** y ya pude extraer **{sync.get('resolved_field')}**. ¡Listo! Ya no hay pendientes en cola por este bloque."`.
    - Caso 3 (no encontrado): `f"Reprocesé el archivo **{filename}**, pero aún no encuentro **{label}** con claridad. ¿Podrías escribírmelo aquí?"`.
    - Caso 4 (sin pendientes o sin `company_id`): `f"Documento '{filename}' analizado con éxito."`.
    - _Requisitos: 6.1, 6.2, 6.3, 6.4_

  - [x] 6.3 Verificar que `post_analysis_sync` siempre se incluye en `data`
    - Asegurar que todos los `return GenericResponse(...)` del endpoint incluyen `"post_analysis_sync": sync` en el campo `data`, incluyendo el path `ANALYZED` y el path de error del hook.
    - _Requisitos: 6.5_

  - [ ]* 6.4 Escribir pruebas unitarias para el endpoint
    - `test_exception_caught_by_endpoint`: hook que lanza excepción → HTTP 200, `success=True`, `reason="hook_exception"` en `data`.
    - `test_message_format_resolved_with_next`: mensaje contiene `filename`, `field_label` y `next_label`.
    - `test_message_format_resolved_no_next`: mensaje contiene `filename` y `field_label`, sin referencia a siguiente.
    - `test_message_format_not_found`: mensaje contiene `filename` y `pending_label`.
    - `test_post_analysis_sync_always_in_data`: `data` siempre contiene `post_analysis_sync` con los 6 campos requeridos.
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2_

- [ ] 7. Escribir pruebas de propiedades con Hypothesis
  - Crear `backend/tests/property/test_auto_resolve_properties.py`.
  - [ ]* 7.1 Propiedad 1 — Ausencia de `company_id` siempre retorna `missing_company_id`
    - Generar `session_state` con `pending_questions` no vacías de tipo `"profile"` y `company_id` en `{None, "", "   "}`.
    - Verificar `resolved_current_pending=False`, `reason="missing_company_id"`, sin llamadas a `save_company` ni `save_session`.
    - **Propiedad 1: Ausencia de company_id siempre retorna missing_company_id**
    - **Valida: Requisito 1.4**

  - [ ]* 7.2 Propiedad 2 — Sin pendientes activos siempre retorna `no_pending_questions`
    - Generar `company_id` válido y `session_state` con `pending_questions` vacío o `None`.
    - Verificar `resolved_current_pending=False`, `reason="no_pending_questions"`, sin invocar `DataGapAgent`.
    - **Propiedad 2: Sin pendientes activos siempre retorna no_pending_questions**
    - **Valida: Requisito 2.1**

  - [ ]* 7.3 Propiedad 3 — Tipo no-profile siempre retorna `current_pending_not_profile`
    - Generar pendiente activo con `type` distinto de `"profile"` (incluyendo `"economic_price"` y strings arbitrarios).
    - Verificar `resolved_current_pending=False`, `reason="current_pending_not_profile"`, sin invocar `DataGapAgent`.
    - **Propiedad 3: Tipo no-profile siempre retorna current_pending_not_profile**
    - **Valida: Requisitos 2.2, 8.4**

  - [ ]* 7.4 Propiedad 4 — El índice calculado siempre está en rango válido
    - Generar `pending_length ∈ [1, 50]` y `raw_index ∈ [-100, 100]`.
    - Verificar que `max(0, min(raw_index, pending_length - 1)) ∈ [0, pending_length - 1]`.
    - **Propiedad 4: El índice calculado siempre está en rango válido**
    - **Valida: Requisito 2.4**

  - [ ]* 7.5 Propiedad 5 — Valor inválido no modifica `master_profile` ni `session_state`
    - Generar `field_key`, pendiente de tipo `"profile"` y valores que no pasan `_is_data_valid` (`None`, `""`, longitud < 2, strings con `"["` o `"placeholder"`).
    - Verificar `reason="value_not_found_or_invalid"`, `master_profile` y `session_state` sin cambios.
    - **Propiedad 5: Valor inválido no modifica master_profile ni session_state**
    - **Valida: Requisitos 3.2, 3.3**

  - [ ]* 7.6 Propiedad 6 — Persistencia preserva campos existentes de `master_profile`
    - Generar `existing_profile` con campos arbitrarios y un `field_key` nuevo con valor válido.
    - Verificar que todos los campos distintos de `field_key` conservan sus valores originales tras la actualización.
    - **Propiedad 6: Persistencia preserva campos existentes de master_profile**
    - **Valida: Requisito 4.3**

  - [ ]* 7.7 Propiedad 7 — Avance de cola reduce la lista en exactamente un elemento
    - Generar lista de pendientes de longitud `N ∈ [1, 20]` e índice `raw_idx ∈ [0, 19]`.
    - Verificar que `len(new_pending) == N - 1` y que `new_idx ∈ [0, max(0, N-2)]`.
    - **Propiedad 7: Avance de cola reduce la lista en exactamente un elemento**
    - **Valida: Requisitos 5.1, 5.2**

  - [ ]* 7.8 Propiedad 11 — Idempotencia del hook
    - Primera ejecución con pendiente activo de tipo `"profile"` y valor válido → `resolved_current_pending=True`.
    - Segunda ejecución sobre el mismo estado → `reason="no_pending_questions"`, `master_profile[field_key]` conserva el valor de la primera ejecución.
    - **Propiedad 11: Idempotencia del hook**
    - **Valida: Requisito 7.4**

- [x] 8. Checkpoint final — Asegurar que todas las pruebas pasan
  - Ejecutar `pytest backend/tests/unit/test_auto_resolve_hook.py backend/tests/property/test_auto_resolve_properties.py -v` y verificar que no hay fallos.
  - Consultar al usuario si alguna prueba requiere ajuste de mocks o fixtures.

## Notas

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido.
- El código base en `upload.py` ya cubre el camino feliz; las tareas 1–4 son robustecimientos incrementales, no reescrituras.
- Cada tarea referencia los requisitos específicos para trazabilidad.
- Las propiedades de Hypothesis usan `@settings(max_examples=100)` como mínimo; la Propiedad 4 y 7 usan 200 por su naturaleza aritmética.
- Los mocks de `memory` deben exponer `save_company_called` y `save_session_called` como flags para verificar ausencia de I/O en retornos tempranos.
