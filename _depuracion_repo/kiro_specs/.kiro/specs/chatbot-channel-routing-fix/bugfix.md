# Bugfix Requirements: Chatbot Channel Routing Fix

## Introducción

`ChatbotRAGAgent` presenta dos bugs de enrutamiento que causan 8 tests fallidos en `test_chatbot_rag_behavior.py`:

**Bug A (Prioridad Alta):** El canal económico (`SPRINT 3`) intercepta mensajes de perfil corporativo antes de que lleguen al canal de captura de datos de perfil (`FASE 3A`). Cuando hay `pending_questions` de tipo `profile_field` y el usuario responde con frases como `"mi rfc es ABC123456XYZ"` o `"mi tel es 555"`, la heurística rápida de `_classify_message` devuelve `DATA_INTAKE`, pero el canal económico ya procesó el mensaje antes y devuelve `"clarification_needed"` porque no puede extraer un precio.

**Bug B (Prioridad Media):** El `chatbot_final_guard_injection` convierte el `intake_plan` a `pending_questions` antes de que el bloque de "oferta proactiva" (`intake_proactive_offer`) tenga oportunidad de ejecutarse. Esto hace que el flujo de opt-in (donde el usuario debe aceptar el plan antes de que se inyecten las preguntas) quede cortocircuitado: el chatbot va directo a `pending_question` en lugar de presentar la oferta.

**Bug C (Prioridad Media):** Los textos de rescate económico (`economic_blocking_rescue_hint`) cambiaron en implementaciones posteriores pero los tests no fueron actualizados. Adicionalmente, un test tiene la lógica invertida: espera `rag_answer` cuando el comportamiento correcto es `economic_blocking_rescue_hint`.

---

## Alcance del bugfix

- **Sí cambia:** orden de evaluación del canal económico vs canal de perfil en `process()`.
- **Sí cambia:** condición de activación del `final_guard` para respetar el flujo de opt-in.
- **Sí cambia:** assertions de tests que describen comportamiento que evolucionó.
- **No cambia:** lógica de extracción económica ni de captura de perfil.
- **No cambia:** contratos de `AgentOutput` ni de `session_state`.

---

## Bug Analysis

### Bug A — Canal económico intercepta mensajes de perfil

#### Current Behavior (Defect)

A.1 WHEN hay `pending_questions` de tipo `profile_field` y el usuario envía `"mi rfc es ABC123456XYZ"`, THEN el canal económico (`SPRINT 3`) clasifica el mensaje como `DATA_INTAKE` vía heurística rápida (detecta `"mi "`) y llama a `_extract_economic_data_llm`.

A.2 WHEN `_extract_economic_data_llm` no puede extraer un precio del mensaje de perfil, THEN el sistema retorna `"clarification_needed"` con el mensaje "no logro distinguir el precio de las especificaciones técnicas".

A.3 WHEN el usuario responde `"mi tel es 555"` con un único pendiente de tipo `profile_field`, THEN el sistema retorna `"clarification_needed"` en lugar de guardar el teléfono y cerrar el expediente.

#### Expected Behavior (Correct)

A.4 WHEN hay `pending_questions` de tipo `profile_field` activo y el usuario envía un mensaje de datos, THEN el canal económico SHALL omitir la clasificación `DATA_INTAKE` y dejar que el flujo llegue a `FASE 3A` (`_handle_data_intake`).

A.5 WHEN el canal económico evalúa si debe procesar un mensaje, THEN SHALL verificar que la pregunta pendiente actual sea de tipo económico (`economic_price` o `economic_validation_blocking`) antes de intentar extracción de precio.

A.6 WHEN el mensaje llega a `FASE 3A` con `mode == DATA_INTAKE` y la pregunta pendiente es de tipo `profile_field`, THEN `_handle_data_intake` SHALL procesar el dato de perfil correctamente.

### Bug B — Final guard cortocircuita el flujo de opt-in

#### Current Behavior (Defect)

B.1 WHEN `session_state` tiene `intake_plan` con preguntas y NO tiene `pending_questions`, THEN `chatbot_final_guard_injection` convierte el plan a `pending_questions` inmediatamente, antes de que el bloque de oferta proactiva evalúe si debe presentar el opt-in.

B.2 WHEN el usuario envía `"hola"` con `intake_plan` activo pero sin haber aceptado el plan, THEN el sistema devuelve `pending_question` (primera pregunta del plan) en lugar de `intake_proactive_offer` (oferta de iniciar el plan).

#### Expected Behavior (Correct)

B.3 WHEN `session_state` tiene `intake_plan` pero `intake_progress.accepted` es `False` o no existe, THEN el `final_guard` SHALL NO inyectar las preguntas del plan en `pending_questions`.

B.4 WHEN el usuario envía un saludo con `intake_plan` activo y no aceptado, THEN el sistema SHALL presentar `intake_proactive_offer` con el resumen del plan.

B.5 WHEN el usuario acepta el plan (opt-in), THEN el sistema SHALL convertir el `intake_plan` a `pending_questions` y comenzar el flujo secuencial.

### Bug C — Assertions de tests desactualizadas

#### Current Behavior (Defect)

C.1 WHEN el sistema genera el mensaje de rescate económico para `economic_validation_blocking`, THEN el texto actual es `"para avanzar, necesito confirmar el precio de: «concepto»"` pero los tests esperan `"necesito el precio para"`.

C.2 WHEN `blocking_items` no tiene `concepto_label` legible (solo `concepto_id`), THEN el sistema devuelve `tipo: "pending_economic_list"` pero el test espera `tipo: "economic_blocking_rescue_hint"`.

C.3 WHEN el label de `blocking_items` es un agregado como `"3 partidas"`, THEN el sistema lo muestra en el mensaje pero el test espera que no aparezca.

C.4 WHEN hay `economic_validation_blocking` activo y el usuario envía `"ya me lo dijiste, dime cuales!"`, THEN el sistema devuelve `economic_blocking_rescue_hint` (correcto) pero el test espera `rag_answer` (incorrecto — el test tiene la lógica invertida).

#### Expected Behavior (Correct)

C.5 Los tests SHALL reflejar el comportamiento actual del sistema, no el comportamiento de una versión anterior.

C.6 El test `test_blocking_pending_forza_rescate_y_no_deriva_a_rag` SHALL verificar que el sistema devuelve `economic_blocking_rescue_hint` (no `rag_answer`) cuando hay bloqueo económico activo.

---

## Unchanged Behavior (Regression Prevention)

5.1 WHEN la pregunta pendiente es de tipo `economic_price` y el usuario envía un número, THEN el canal económico SHALL CONTINUE TO procesarlo como precio.

5.2 WHEN la pregunta pendiente es de tipo `economic_validation_blocking`, THEN el canal económico SHALL CONTINUE TO manejar el rescate de precios.

5.3 WHEN el usuario acepta el `intake_plan` con opt-in, THEN el sistema SHALL CONTINUE TO convertir el plan a `pending_questions` y comenzar el flujo.

5.4 WHEN `intake_progress.accepted` es `True`, THEN el `final_guard` SHALL CONTINUE TO inyectar preguntas del plan si no hay preguntas forenses en la cola.

5.5 WHEN el usuario envía `"no aplica"` o `"omitir"` con un pendiente activo, THEN la omisión auditada SHALL CONTINUE TO funcionar correctamente.

---

## Criterios de aceptación

6.1 Con `pending_questions` de tipo `profile_field` y mensaje `"mi rfc es ABC123456XYZ"`:
- El sistema guarda el RFC en `master_profile`.
- La respuesta confirma el guardado y pregunta el siguiente campo.
- `tipo` es `"data_saved"`.

6.2 Con `pending_questions` de tipo `profile_field` (único) y mensaje `"mi tel es 555"`:
- El sistema guarda el teléfono.
- La respuesta contiene el mensaje de expediente completo.
- `tipo` es `"data_saved"`.

6.3 Con `intake_plan` activo, sin `intake_progress.accepted`, y mensaje `"hola"`:
- El sistema devuelve `tipo: "intake_proactive_offer"`.
- El mensaje contiene "bloqueante" y "diagnóstico listo".

6.4 Con `economic_validation_blocking` activo y mensaje `"que precios necesitas?"`:
- El sistema devuelve `tipo` en `("economic_validation_blocking_info", "economic_blocking_rescue_hint")`.
- El mensaje contiene el nombre del concepto bloqueado.

6.5 Los 8 tests en `test_chatbot_rag_behavior.py` pasan sin modificar la lógica de negocio.

---

## Plan mínimo de pruebas de regresión

7.1 Los 8 tests fallidos deben pasar tras el fix.
7.2 Los 38 tests que ya pasan no deben regresar.
7.3 Verificar manualmente que el flujo de captura de RFC funciona en sesión real.
