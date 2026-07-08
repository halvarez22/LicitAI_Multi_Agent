# Bugfix Requirements Document

## Introducción

El `DataGapAgent` presenta una divergencia respecto a los specs de `chatbot-data-collection`: actualmente solo encola en `pending_questions` los campos definidos en `BLOCKING_FIELDS` (`rfc`, `razon_social`, `domicilio_fiscal`, `representante_legal`), ignorando faltantes no bloqueantes (`telefono`, `email`, `web`, `anos_experiencia`, etc.).

Esto rompe el flujo HITL esperado ("todo faltante se solicita al usuario por asistente") y provoca generación de documentos con expediente parcialmente incompleto sin interacción explícita del usuario.

---

## Alcance del bugfix

- **Sí cambia:** política de encolado de brechas para conversación (`pending_questions`).
- **No cambia:** criterio de bloqueo de generación documental (sigue gobernado por campos críticos).
- **No cambia:** heurísticas de auto-extracción RAG y validación `_is_data_valid`.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `DataGapAgent` detecta un faltante fuera de `BLOCKING_FIELDS` y no puede auto-extraerlo desde RAG, THEN el sistema lo omite de `pending_questions` sin pregunta al usuario.

1.2 WHEN `DataGapAgent` procesa campos de `INFORMATIONAL_FIELDS` vacíos o inválidos, THEN registra log informativo y continúa sin encolarlos.

1.3 WHEN el usuario conversa tras análisis de brechas, THEN `ChatbotRAG` solo pregunta faltantes críticos y no recorre faltantes informativos.

### Expected Behavior (Correct)

2.1 WHEN `DataGapAgent` detecta cualquier faltante (crítico o informativo) que no puede auto-extraer ni validar, THEN el sistema SHALL encolarlo en `pending_questions`.

2.2 WHEN `DataGapAgent` encola faltantes, THEN SHALL construir preguntas con `FIELD_DEFINITIONS` para mantener lenguaje y hints coherentes.

2.3 WHEN `ChatbotRAG` encuentra `pending_questions`, THEN SHALL preguntar de forma secuencial una por turno hasta agotar la cola o recibir instrucción explícita de omisión para campos no bloqueantes.

2.4 WHEN no hay `pending_questions` y el usuario envía saludo/consulta vacía, THEN `ChatbotRAG` SHALL invocar `DataGapAgent` proactivamente y exponer la primera pregunta pendiente en la misma respuesta.

---

## Contrato funcional de datos (nuevo)

3.1 WHEN `DataGapAgent` finaliza evaluación, THEN `AgentOutput.data.missing` SHALL contener **todos** los faltantes detectados (bloqueantes + no bloqueantes).

3.2 WHEN `DataGapAgent` finaliza evaluación, THEN `AgentOutput.data.missing_blocking` SHALL contener solo el subconjunto crítico para gate documental.

3.3 WHEN se persiste estado de sesión, THEN `session_state.pending_questions` SHALL derivar de `missing` (no de `missing_blocking`).

3.4 WHEN un campo se auto-extrae válidamente, THEN no debe existir simultáneamente en `auto_filled` y `missing`.

---

## Reglas de conversación secuencial

4.1 WHEN hay `pending_questions`, THEN `ChatbotRAG` SHALL formular únicamente la pregunta actual (`pending_question_index`) para evitar batching confuso.

4.2 WHEN el usuario responde un campo pendiente y la persistencia es exitosa, THEN el sistema SHALL avanzar al siguiente pendiente y confirmar brevemente el guardado.

4.3 WHEN el usuario indica omitir un campo no bloqueante, THEN el sistema SHALL marcarlo como omitido/auditado y avanzar sin bloquear generación.

4.4 WHEN el usuario intenta omitir un campo bloqueante durante generación, THEN el sistema SHALL mantener estado `WAITING_FOR_DATA` con mensaje UX explícito del bloqueo.

---

## Unchanged Behavior (Regression Prevention)

5.1 WHEN falta un campo en `BLOCKING_FIELDS`, THEN el sistema SHALL CONTINUE TO bloquear generación (`WAITING_FOR_DATA`) hasta completar ese dato.

5.2 WHEN un campo se auto-extrae desde RAG (crítico o no crítico), THEN el sistema SHALL CONTINUE TO persistirlo en `master_profile` sin preguntar.

5.3 WHEN `_is_data_valid` evalúa un valor, THEN el sistema SHALL CONTINUE TO aplicar reglas actuales de sanitización y rechazo de placeholders/basura.

5.4 WHEN `OrchestratorAgent` decide continuidad de pipeline, THEN el sistema SHALL CONTINUE TO usar solo `missing_blocking`/`BLOCKING_FIELDS` para bloqueo duro.

5.5 WHEN se generan documentos administrativos autogenerables (ej. cartas de protesta, integridad, no conflicto), THEN el sistema SHALL CONTINUE TO generarlos desde datos de perfil sin exigir upload manual.

---

## Criterios de aceptación

6.1 Dado un perfil con faltantes no bloqueantes (`telefono`, `email`), al ejecutar DataGap:
- `missing` incluye esos campos.
- `pending_questions` incluye esos campos en orden estable.
- no se activa bloqueo por esos campos.

6.2 Dado un perfil con faltante bloqueante (`rfc`), al ejecutar generación:
- estado final es `WAITING_FOR_DATA`.
- chatbot formula pregunta específica de `rfc`.

6.3 Dado un perfil con faltantes mixtos (bloqueantes + informativos), el chatbot:
- pregunta secuencialmente ambos tipos,
- permite omitir informativos,
- no permite completar generación si persisten bloqueantes.

6.4 Dado un saludo inicial con cola vacía, el chatbot:
- dispara análisis proactivo de brechas,
- presenta primera pregunta pendiente si se detectan faltantes.

---

## Plan mínimo de pruebas de regresión

7.1 Unit tests `DataGapAgent`
- encolado de faltantes informativos.
- separación correcta `missing` vs `missing_blocking`.
- consistencia `auto_filled` excluye faltantes.

7.2 Unit tests `ChatbotRAG`
- saludo con cola pendiente pregunta item 1.
- saludo sin cola invoca DataGap y pregunta item 1.
- avance secuencial tras persistencia.

7.3 Integration/E2E
- sesión con faltantes no bloqueantes llega a generación con advertencia conversacional previa.
- sesión con faltantes bloqueantes queda en `WAITING_FOR_DATA`.
- no se solicitan como upload documentos que la app debe autogenerar.
