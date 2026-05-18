# Documento de Requisitos: Sincronización de Precios Chat → Generación de Documentos

## Introducción

LicitAI presenta un bug crítico de sincronización entre la fase de captura de precios vía chatbot y la fase de generación de documentos. Cuando el usuario captura precios económicos a través del chat, estos se persisten en `session_state.economic_user_inputs.concept_prices`, pero el `EconomicWriterAgent` lee los datos desde `tasks_completed["economic_proposal"]` — un snapshot generado **antes** de que el usuario proporcionara los precios. El resultado es que el generador de documentos ve `total_base = 0` y bloquea la generación, aunque el UI muestre "✅ Propuesta económica calculada".

Este spec cubre las correcciones necesarias para garantizar que los precios capturados vía chat se propaguen correctamente al pipeline de generación de documentos, que el estado del UI sea consistente con la fuente de verdad del motor, y que el flujo completo sea verificable mediante tests de integración.

---

## Glosario

- **economic_user_inputs**: Diccionario en `session_state` donde el chatbot persiste los precios capturados por el usuario (`concept_prices`, `subtotal_propuesta`, etc.).
- **tasks_completed["economic_proposal"]**: Snapshot JSON persistido por `EconomicAgent` en PostgreSQL que contiene `items`, `total_base`, `grand_total` y `status`. Es la fuente de verdad que consume `EconomicWriterAgent`.
- **EconomicAgent**: Agente que calcula la propuesta económica completa, detecta gaps de precio y persiste el resultado en `tasks_completed["economic_proposal"]`.
- **EconomicWriterAgent**: Agente que genera los documentos físicos (XLSX + DOCX) a partir del snapshot en `tasks_completed["economic_proposal"]`.
- **EconomicRefresherService**: Servicio que aplica overrides del usuario sobre un snapshot existente sin re-ejecutar el LLM.
- **refresh_economic_validations_for_session**: Función que revalida el snapshot existente pero NO recalcula ítems ni totales.
- **allow_zero_total_base_ack**: Flag HITL en `session_state.economic_user_inputs` que permite generar documentos con subtotal ~0 cuando la convocatoria lo admite.
- **Snapshot desactualizado**: Condición en la que `tasks_completed["economic_proposal"]` contiene `total_base = 0` o ítems con `precio_unitario = 0` porque fue generado antes de que el usuario capturara precios.
- **generation_only**: Modo del orquestador que salta las fases de análisis y compliance y ejecuta directamente el pipeline de generación, asumiendo que los datos previos están listos.

---

## Requisitos

### Requisito 1: Re-ejecución de EconomicAgent al capturar precios vía chat

**User Story:** Como usuario de LicitAI, quiero que al proporcionar un precio en el chat, el sistema actualice automáticamente la propuesta económica calculada, para que al generar documentos se usen mis precios reales y no valores en cero.

#### Criterios de Aceptación

1. WHEN el usuario captura uno o más precios vía `_handle_economic_transaction` en el chatbot, THE sistema SHALL invocar `EconomicAgent.process()` para recalcular la propuesta completa con los nuevos precios antes de retornar la respuesta al usuario.
2. WHEN `EconomicAgent` se re-ejecuta tras captura de precios, THE `EconomicAgent` SHALL leer los overrides desde `session_state.economic_user_inputs` y aplicarlos sobre los ítems de la propuesta.
3. WHEN la re-ejecución de `EconomicAgent` produce un resultado con `status == "complete"` y `total_base > 0`, THE sistema SHALL persistir el nuevo snapshot en `tasks_completed["economic_proposal"]` sobreescribiendo el anterior.
4. WHEN la re-ejecución de `EconomicAgent` falla o retorna `WAITING_FOR_DATA`, THE sistema SHALL mantener el snapshot anterior en `tasks_completed` y notificar al usuario cuántos precios faltan aún.
5. IF la re-ejecución de `EconomicAgent` tarda más de 30 segundos, THEN THE sistema SHALL retornar la confirmación de captura al usuario de forma inmediata y ejecutar la re-ejecución en background, actualizando el snapshot cuando termine.
6. WHEN la re-ejecución de `EconomicAgent` completa exitosamente en background, THE sistema SHALL actualizar `session_state.economic_proposal_ready = True` para que el frontend pueda detectar el cambio.

---

### Requisito 2: Corrección del EconomicRefresherService para recalcular totales

**User Story:** Como desarrollador, quiero que el refresher económico recalcule los totales reales de la propuesta al aplicar overrides del usuario, para que `total_base` refleje los precios capturados y no permanezca en cero.

#### Criterios de Aceptación

1. WHEN `refresh_economic_validations_for_session` es invocado después de capturar precios, THE función SHALL aplicar `EconomicRefresherService.apply_overrides()` sobre los ítems del snapshot antes de recalcular totales.
2. WHEN `apply_overrides()` actualiza el `precio_unitario` de un ítem, THE servicio SHALL recalcular el `subtotal` del ítem como `cantidad * precio_unitario` y actualizar `total_base` como la suma de todos los subtotales.
3. WHEN el refresher recalcula `total_base`, THE servicio SHALL persistir el snapshot actualizado en `tasks_completed["economic_proposal"]` con el nuevo `total_base` y `grand_total`.
4. WHEN el refresher actualiza el snapshot, THE servicio SHALL preservar todos los campos existentes del snapshot (`validation_result`, `calculator_result`, `quadrature_report`, etc.) y solo actualizar `items`, `total_base`, `grand_total` y `status`.
5. IF `tasks_completed["economic_proposal"]` no existe al invocar el refresher, THEN THE función SHALL retornar sin error y sin crear un snapshot vacío.

---

### Requisito 3: Consistencia del estado del UI con la fuente de verdad del motor

**User Story:** Como usuario, quiero que el panel de "Propuesta económica" en el UI refleje el estado real del motor económico, para no ver "✅ Propuesta calculada" cuando en realidad el subtotal es cero.

#### Criterios de Aceptación

1. WHEN el UI muestra el estado de la propuesta económica, THE UI SHALL leer el estado desde `tasks_completed["economic_proposal"].status` y `total_base`, no desde `economic_user_inputs`.
2. WHEN `tasks_completed["economic_proposal"].total_base` es menor a `0.01` y `allow_zero_total_base_ack` es `False`, THE UI SHALL mostrar el estado como "⚠️ Precios pendientes" en lugar de "✅ Propuesta económica calculada".
3. WHEN `tasks_completed["economic_proposal"].status == "complete"` y `total_base >= 0.01`, THE UI SHALL mostrar "✅ Propuesta económica calculada" con el monto total.
4. WHEN `tasks_completed["economic_proposal"].status == "waiting_for_data"`, THE UI SHALL mostrar "🔄 Capturando precios..." con el número de precios pendientes.
5. THE UI SHALL actualizar el estado de la propuesta económica en tiempo real cuando `session_state.economic_proposal_ready` cambie a `True`.

---

### Requisito 4: Validación de snapshot en el orquestador antes de generation_only

**User Story:** Como desarrollador, quiero que el orquestador verifique que el snapshot económico está listo antes de invocar al EconomicWriterAgent, para evitar que el generador falle silenciosamente con un subtotal en cero.

#### Criterios de Aceptación

1. WHEN el orquestador entra en modo `generation_only`, THE orquestador SHALL verificar que `tasks_completed["economic_proposal"]` existe y tiene `status == "complete"` antes de invocar a `EconomicWriterAgent`.
2. WHEN `tasks_completed["economic_proposal"]` tiene `total_base < 0.01` y `allow_zero_total_base_ack == False`, THE orquestador SHALL re-ejecutar `EconomicAgent` en lugar de invocar directamente a `EconomicWriterAgent`.
3. WHEN la re-ejecución de `EconomicAgent` desde el orquestador produce `status == "complete"`, THE orquestador SHALL continuar el pipeline de generación normalmente.
4. WHEN la re-ejecución de `EconomicAgent` desde el orquestador retorna `WAITING_FOR_DATA`, THE orquestador SHALL detener el pipeline y retornar al usuario la lista de precios pendientes con instrucciones claras.
5. IF `tasks_completed["economic_proposal"]` no existe en modo `generation_only`, THEN THE orquestador SHALL retornar `stop_reason="MISSING_ECONOMIC_PROPOSAL"` con mensaje descriptivo para el usuario.

---

### Requisito 5: Limpieza de pending_questions económicas al cambiar de sesión

**User Story:** Como usuario, quiero que al abrir una licitación diferente el chatbot me haga preguntas sobre esa licitación y no sobre una anterior, para no confundirme con partidas que no corresponden a mi expediente actual.

#### Criterios de Aceptación

1. WHEN el usuario activa una sesión diferente a la sesión activa anterior, THE sistema SHALL limpiar o regenerar `pending_questions` de tipo `economic_price` y `economic_validation_blocking` desde el `tasks_completed["economic_proposal"]` de la nueva sesión.
2. WHEN se limpian las `pending_questions` económicas al cambiar de sesión, THE sistema SHALL preservar las `pending_questions` de tipo distinto a económico (ej: `master_profile`, `legal`) que correspondan a la nueva sesión.
3. WHEN el chatbot formula una pregunta de precio, THE chatbot SHALL verificar que el `concepto` de la pregunta existe en los `items` del snapshot `tasks_completed["economic_proposal"]` de la sesión activa antes de presentarla al usuario.
4. IF una `pending_question` de tipo `economic_price` no tiene correspondencia en los `items` del snapshot de la sesión activa, THEN THE sistema SHALL descartar esa pregunta silenciosamente y avanzar a la siguiente.

---

### Requisito 6: Acción explícita en UI para allow_zero_total_base_ack

**User Story:** Como usuario, quiero poder confirmar desde el chat que mi licitación no requiere importe base, sin necesidad de conocer términos técnicos internos del sistema, para desbloquear la generación de documentos en ese caso especial.

#### Criterios de Aceptación

1. WHEN `EconomicWriterAgent` retorna el mensaje de error por subtotal ~0, THE sistema SHALL incluir en la respuesta al usuario una opción de confirmación con lenguaje de negocio: "Esta licitación no requiere importe base — confirmar".
2. WHEN el usuario confirma que la licitación no requiere importe base, THE sistema SHALL invocar el endpoint `POST /sessions/{session_id}/economic-hitl/zero-total-base-ack` y persistir `allow_zero_total_base_ack = True` en `session_state.economic_user_inputs`.
3. WHEN `allow_zero_total_base_ack` es `True`, THE sistema SHALL reintentar automáticamente la generación de documentos sin requerir acción adicional del usuario.
4. THE sistema SHALL nunca exponer el nombre técnico del flag (`allow_zero_total_base_ack`) en mensajes visibles al usuario final.

---

### Requisito 7: Test de integración del flujo completo chat → generación

**User Story:** Como desarrollador, quiero tener un test de integración que cubra el flujo completo desde la captura de precios vía chat hasta la generación exitosa de documentos, para prevenir regresiones del bug de sincronización.

#### Criterios de Aceptación

1. THE suite de tests SHALL incluir un test de integración que simule: `EconomicAgent` con gaps de precio → chatbot captura precios → `generation_only` → `EconomicWriterAgent` produce documentos con `subtotal > 0`.
2. THE test SHALL verificar que `tasks_completed["economic_proposal"].total_base` es mayor a `0.01` después de que el chatbot captura precios.
3. THE test SHALL verificar que `EconomicWriterAgent` retorna `AgentStatus.SUCCESS` cuando el snapshot tiene `total_base > 0`.
4. THE test SHALL verificar que el orquestador en modo `generation_only` re-ejecuta `EconomicAgent` cuando el snapshot tiene `total_base = 0`.
5. THE test SHALL cubrir el caso edge de `allow_zero_total_base_ack = True` verificando que `EconomicWriterAgent` genera documentos sin error aunque `total_base = 0`.
