# Plan de Implementación: conversational-mission-engine

## Tareas

- [x] 1. Implementar `_humanize_field_target` (Componente 3)
  - Agregar el método estático `_humanize_field_target` a `ChatbotRAGAgent` en `chatbot_rag.py`
  - Incluir el mapa de claves exactas (`_EXACT_MAP`) con al menos 11 entradas conocidas
  - Incluir el mapa de prefijos de namespace (`_PREFIX_MAP`) con los 6 prefijos conocidos
  - Implementar la limpieza genérica como fallback (eliminar namespace + reemplazar `_` por espacios)
  - Manejar inputs vacíos/None retornando `"Dato requerido"`
  - **Archivo:** `backend/app/agents/chatbot_rag.py`

- [x] 2. Implementar `_build_mission_context` (Componente 1)
  - Agregar el método de instancia `_build_mission_context` a `ChatbotRAGAgent`
  - Leer `documentos_generados` desde `session_state["tasks_completed"]` buscando `stage_completed:`
  - Leer `semaforo_actual` desde `session_state["go_no_go_result"]["semaforo"]` con fallback a `""`
  - Leer `provenance_reason` desde `pending_question["provenance_ui"]["reason"]` con fallback a `""`
  - Calcular `impacto` como `"BLOQUEANTE"` o `"complementario"` según `is_blocking`
  - Calcular `progreso` como `"N de M"` con `current_idx + 1` y `total`
  - Garantizar que no lanza excepciones para ninguna combinación de inputs válidos
  - **Archivo:** `backend/app/agents/chatbot_rag.py`

- [x] 3. Implementar `_detect_tone_mode` (Componente 4)
  - Agregar el método estático `_detect_tone_mode` a `ChatbotRAGAgent`
  - Detectar `modo_post_generacion` cuando `tasks_completed` tiene `stage_completed:*` (prioridad máxima)
  - Detectar `modo_completado` cuando `pending_questions` está vacío
  - Detectar `modo_recoleccion_urgente` cuando el pendiente actual tiene `is_blocking=True`
  - Detectar `modo_recoleccion_inicial` como modo por defecto
  - Garantizar que no lanza excepciones para ninguna combinación de inputs válidos
  - **Archivo:** `backend/app/agents/chatbot_rag.py`

- [x] 4. Implementar el prompt contextualizado para formular preguntas (Componente 2)
  - Agregar el método `_generate_mission_question` a `ChatbotRAGAgent` que recibe `mission_context` y `tone_mode`
  - Implementar el system prompt con las reglas estrictas (máx 3 oraciones, sin variables técnicas, español mexicano)
  - Implementar el user prompt template con los 7 campos del `mission_context`
  - Implementar validación post-generación: si la respuesta contiene `\w+\.\w+`, usar fallback
  - Implementar fallback a `conversation_normalizer.normalize_capture_message` cuando el LLM falla
  - **Archivo:** `backend/app/agents/chatbot_rag.py`

- [x] 5. Integrar el motor conversacional en los puntos de formulación de preguntas (Componente 5)
  - Integrar en el bloque "Caso B: Otros pendientes" del método `process` (saludo/intención con pendientes)
  - Integrar en el bloque de consulta vacía con pendientes activos (bootstrap de sesión)
  - Integrar en `_apply_saved_pending_value` → rama `if fresh_pending` (transición tras guardado)
  - Asegurar que los flujos `economic_validation_blocking` y `economic_price` NO se modifican
  - Asegurar que el mensaje post-generación usa `modo_post_generacion` en lugar del texto frío
  - **Archivo:** `backend/app/agents/chatbot_rag.py`

- [x] 6. Escribir tests de propiedades con Hypothesis
  - Crear `backend/tests/test_conversational_mission_engine.py`
  - Implementar Propiedad 1: `_humanize_field_target` nunca retorna namespace técnico (`\w+\.\w+`)
  - Implementar Propiedad 2: modo `modo_post_generacion` cuando hay `stage_completed:*` en `tasks_completed`
  - Implementar Propiedad 3: modo `modo_recoleccion_urgente` cuando `is_blocking=True` sin docs generados
  - Implementar Propiedad 4: `_humanize_field_target` nunca retorna namespace para ningún input
  - Implementar Propiedad 5: modo `modo_recoleccion_inicial` cuando no hay docs y dato no bloqueante
  - Implementar Propiedad 6: `_build_mission_context` siempre retorna exactamente 7 claves
  - Usar `@settings(max_examples=100)` como mínimo en cada test
  - Usar el tag `# Feature: conversational-mission-engine, Propiedad N` en cada test
  - **Archivo:** `backend/tests/test_conversational_mission_engine.py`

- [x] 7. Escribir tests unitarios
  - `test_humanize_field_target_exact_match`: verificar mapeo exacto para las 11 claves conocidas
  - `test_humanize_field_target_prefix_match`: verificar mapeo por prefijo para los 6 namespaces
  - `test_humanize_field_target_generic_cleanup`: verificar limpieza genérica para claves desconocidas
  - `test_humanize_field_target_empty_input`: verificar retorno de `"Dato requerido"` para inputs vacíos
  - `test_build_mission_context_blocking`: verificar `impacto="BLOQUEANTE"` cuando `is_blocking=True`
  - `test_build_mission_context_docs_generated`: verificar `documentos_generados=True` con `stage_completed`
  - `test_build_mission_context_empty_state`: verificar que no lanza excepciones con `session_state={}`
  - `test_detect_tone_mode_post_generacion`: verificar modo con docs generados
  - `test_detect_tone_mode_urgente`: verificar modo con dato bloqueante sin docs
  - `test_detect_tone_mode_completado`: verificar modo con `pending_questions=[]`
  - `test_detect_tone_mode_inicial`: verificar modo por defecto
  - `test_post_generation_message_not_cold`: verificar que el mensaje post-generación no contiene el texto frío
  - **Archivo:** `backend/tests/test_conversational_mission_engine.py`
