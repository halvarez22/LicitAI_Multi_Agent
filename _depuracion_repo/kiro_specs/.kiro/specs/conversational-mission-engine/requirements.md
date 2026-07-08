# Documento de Requisitos: conversational-mission-engine

## Introducción

El `ChatbotRAGAgent` de LicitAI opera actualmente como un cuestionario secuencial: toma la lista `pending_questions`, formula cada pregunta en orden FIFO usando el campo `question` directamente, y espera respuestas. Esto produce tres síntomas concretos que degradan la experiencia del usuario:

1. **Variables técnicas visibles**: el campo `label` de `pending_questions` usa `field_target` como fallback, por lo que el usuario ve strings como `condiciones_contractuales.penalizaciones` en el chat.
2. **Tono invariante**: el asistente mantiene el mismo "modo interrogatorio" incluso después de generar documentos exitosamente, sin reconocer el logro.
3. **Preguntas descontextualizadas**: el asistente no conecta el dato solicitado con su impacto en la propuesta específica — no dice "necesito tu capital contable porque las bases exigen mínimo $2M", solo formula la pregunta número N de la lista.

Esta feature introduce un **motor conversacional con misión activa** que resuelve los tres síntomas mediante cinco componentes quirúrgicos en `chatbot_rag.py`, sin modificar la arquitectura de `pending_questions` como fuente de verdad ni el flujo de persistencia.

---

## Glosario

- **ChatbotRAGAgent**: Agente conversacional principal (`backend/app/agents/chatbot_rag.py`).
- **pending_questions**: Lista de objetos en `session_state` que representan datos faltantes. Fuente de verdad del flujo de recolección. No se modifica en esta feature.
- **field_target**: Clave técnica de un campo en el `master_profile` (ej: `solvencia_economica.capital_contable`). Nunca debe ser visible para el usuario.
- **label**: Campo de `pending_question` que contiene el nombre legible del dato. Actualmente puede contener el `field_target` como fallback.
- **mission_context**: Diccionario interno (no persistido) que agrega semántica de negocio a una `pending_question` antes de formularla.
- **tone_mode**: Modo de tono detectado según el estado de la sesión. Uno de: `modo_recoleccion_inicial`, `modo_recoleccion_urgente`, `modo_post_generacion`, `modo_completado`.
- **tasks_completed**: Campo de `session_state` que registra las tareas completadas por el pipeline. Indica si se han generado documentos.
- **go_no_go_result**: Campo de `session_state` con el último resultado del semáforo Go/No-Go.
- **provenance_ui**: Campo de `pending_question` generado por el `IntakePlannerAgent` con la razón de negocio del dato solicitado.
- **IntakePlannerAgent**: Agente que genera `pending_questions` con contexto de negocio. No se modifica en esta feature.

---

## Requisitos

### Requisito 1: Traducción de field_targets técnicos a labels legibles

**User Story:** Como usuario de LicitAI, quiero que el chatbot me hable en lenguaje natural sobre los datos que necesita, para no ver variables técnicas del sistema en la conversación.

#### Criterios de Aceptación

1. WHEN el `ChatbotRAGAgent` formula una pregunta pendiente cuyo `label` contiene el patrón `\w+\.\w+` (indicador de namespace técnico), THE `ChatbotRAGAgent` SHALL traducir ese label usando `_humanize_field_target` antes de mostrarlo al usuario.
2. THE método `_humanize_field_target` SHALL mapear claves exactas conocidas a sus labels legibles (ej: `condiciones_contractuales.penalizaciones` → `"Penalizaciones contractuales"`).
3. THE método `_humanize_field_target` SHALL mapear claves por prefijo de namespace cuando no hay match exacto (ej: `solvencia_economica.nuevo_campo` → `"Solvencia económica: Nuevo campo"`).
4. WHEN `_humanize_field_target` recibe un `field_target` no reconocido, THE método SHALL limpiar el string eliminando el prefijo de namespace y reemplazando guiones bajos por espacios.
5. THE método `_humanize_field_target` SHALL NEVER retornar un string que contenga el patrón `\w+\.\w+` (namespace técnico).
6. WHEN `_humanize_field_target` recibe un string vacío o None, THE método SHALL retornar `"Dato requerido"`.

---

### Requisito 2: Formulación contextualizada de preguntas con misión activa

**User Story:** Como usuario, quiero que el chatbot me explique por qué necesita cada dato y cómo impacta en mi propuesta, para entender el valor de proporcionar la información.

#### Criterios de Aceptación

1. WHEN el `ChatbotRAGAgent` formula una pregunta pendiente, THE `ChatbotRAGAgent` SHALL construir un `mission_context` usando `_build_mission_context` antes de generar el mensaje al usuario.
2. WHEN el `mission_context` tiene `documentos_generados=True`, THE mensaje generado SHALL contener una señal de reconocimiento del logro (ej: emoji 🎉, palabras "listos", "generados", "exitosamente") antes de formular la pregunta.
3. WHEN el `mission_context` tiene `impacto="BLOQUEANTE"`, THE mensaje generado SHALL transmitir urgencia sin generar ansiedad (ej: "este dato es clave para poder participar").
4. THE mensaje generado SHALL tener máximo 3 oraciones.
5. THE mensaje generado SHALL estar en español mexicano con tono conversacional.
6. THE mensaje generado SHALL NEVER contener nombres de variables técnicas (field_target, question_type, solvencia_economica, condiciones_contractuales, ni ningún patrón `\w+\.\w+`).
7. WHEN el `mission_context` tiene `provenance_reason` no vacío, THE mensaje generado SHOULD usar esa razón para contextualizar la importancia del dato.

---

### Requisito 3: Contexto de misión completo en `_build_mission_context`

**User Story:** Como desarrollador, quiero que el contexto de misión capture todos los datos relevantes del estado de la sesión, para que el LLM pueda generar mensajes precisos y contextualizados.

#### Criterios de Aceptación

1. THE método `_build_mission_context` SHALL retornar un dict con exactamente las claves: `dato_solicitado`, `por_que_importa`, `impacto`, `progreso`, `documentos_generados`, `semaforo_actual`, `provenance_reason`.
2. THE campo `documentos_generados` SHALL ser `True` si y solo si `session_state["tasks_completed"]` contiene al menos un elemento con `task` que comienza con `"stage_completed:"`.
3. THE campo `impacto` SHALL ser `"BLOQUEANTE"` si `pending_question["is_blocking"]` es truthy, y `"complementario"` en caso contrario.
4. THE campo `progreso` SHALL tener el formato `"N de M"` donde N es `current_idx + 1` y M es `total`.
5. THE campo `semaforo_actual` SHALL leer de `session_state["go_no_go_result"]["semaforo"]` con fallback a string vacío.
6. THE campo `provenance_reason` SHALL leer de `pending_question["provenance_ui"]["reason"]` con fallback a string vacío.
7. WHEN `session_state` está vacío o es None, THE método SHALL retornar el dict con valores por defecto sin lanzar excepciones.

---

### Requisito 4: Detección de modo de tono por estado de sesión

**User Story:** Como usuario, quiero que el chatbot ajuste su tono según el contexto de la sesión, para recibir mensajes apropiados al momento (celebración, urgencia, orientación).

#### Criterios de Aceptación

1. WHEN `session_state["tasks_completed"]` contiene al menos un elemento con `task` que comienza con `"stage_completed:"`, THE `_detect_tone_mode` SHALL retornar `"modo_post_generacion"` independientemente del estado de los pendientes.
2. WHEN no hay documentos generados y la `pending_question` actual tiene `is_blocking=True`, THE `_detect_tone_mode` SHALL retornar `"modo_recoleccion_urgente"`.
3. WHEN no hay documentos generados y la `pending_question` actual tiene `is_blocking=False` o no tiene el campo, THE `_detect_tone_mode` SHALL retornar `"modo_recoleccion_inicial"`.
4. WHEN `pending_questions` está vacío, THE `_detect_tone_mode` SHALL retornar `"modo_completado"`.
5. THE modo `"modo_post_generacion"` tiene prioridad sobre `"modo_recoleccion_urgente"`: si hay documentos generados Y el dato es bloqueante, el modo es `"modo_post_generacion"`.

---

### Requisito 5: Mensaje post-generación contextualizado

**User Story:** Como usuario, quiero que el chatbot celebre cuando mis documentos han sido generados exitosamente, en lugar de continuar en modo interrogatorio como si nada hubiera pasado.

#### Criterios de Aceptación

1. WHEN el pipeline completa la generación de documentos y aún existen `pending_questions`, THE `ChatbotRAGAgent` SHALL formular la siguiente pregunta en modo `"modo_post_generacion"` con tono celebratorio.
2. THE mensaje en modo `"modo_post_generacion"` SHALL reconocer el logro de generación ANTES de solicitar el dato pendiente.
3. THE mensaje en modo `"modo_post_generacion"` SHALL presentar los datos pendientes como "mejoras para blindar la propuesta", no como requisitos bloqueantes.
4. THE mensaje en modo `"modo_post_generacion"` SHALL NEVER usar el texto frío: "Aún quedan datos pendientes del expediente — el asistente continuará solicitándolos para completar el perfil."
5. WHEN el modo es `"modo_completado"` (sin pendientes), THE `ChatbotRAGAgent` SHALL mostrar un mensaje de felicitación con call to action para generar la propuesta.

---

### Requisito 6: Resiliencia y compatibilidad con el pipeline existente

**User Story:** Como desarrollador, quiero que el motor conversacional sea una capa de presentación pura que no rompa ningún flujo existente, para garantizar la estabilidad del sistema en producción.

#### Criterios de Aceptación

1. WHEN el LLM falla al generar el mensaje contextualizado, THE `ChatbotRAGAgent` SHALL degradar graciosamente al comportamiento anterior usando `conversation_normalizer.normalize_capture_message` con el label humanizado.
2. THE motor conversacional SHALL NOT modificar el contenido de `pending_questions` en `session_state` — solo modifica la presentación del mensaje.
3. THE motor conversacional SHALL NOT modificar el flujo de persistencia en `master_profile` ni el índice `current_question_index`.
4. THE motor conversacional SHALL NOT introducir llamadas adicionales al LLM en el flujo de clasificación de mensajes (`_classify_message`).
5. WHEN `_humanize_field_target` recibe cualquier input (incluyendo None, strings vacíos, strings con caracteres especiales), THE método SHALL retornar un string no vacío sin lanzar excepciones.
6. THE `_build_mission_context` SHALL NOT lanzar excepciones para ninguna combinación válida de `session_state` y `pending_question`.
7. THE `_detect_tone_mode` SHALL NOT lanzar excepciones para ninguna combinación válida de `session_state`, `pending_questions` y `current_idx`.

---

### Requisito 7: Integración en los puntos de formulación de preguntas

**User Story:** Como desarrollador, quiero que el motor conversacional se integre en todos los puntos donde el chatbot formula preguntas pendientes, para garantizar consistencia en toda la experiencia.

#### Criterios de Aceptación

1. THE motor conversacional SHALL integrarse en el bloque "Caso B: Otros pendientes" del método `process` (formulación de pregunta cuando el usuario saluda o expresa intención).
2. THE motor conversacional SHALL integrarse en el bloque de consulta vacía con pendientes activos (bootstrap de sesión).
3. THE motor conversacional SHALL integrarse en `_apply_saved_pending_value` → rama `if fresh_pending` (formulación de la siguiente pregunta tras guardar un dato).
4. THE motor conversacional SHALL NOT integrarse en el flujo de preguntas de tipo `economic_validation_blocking` — ese flujo tiene su propio manejo especializado.
5. THE motor conversacional SHALL NOT integrarse en el flujo de preguntas de tipo `economic_price` — ese flujo tiene su propio manejo especializado.
