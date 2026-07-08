# Documento de Requisitos

## Introducción

La feature **Auto-Resolve Pending on Upload** cierra el hueco de experiencia más crítico del flujo HITL de LicitAI: cuando el usuario sube un documento como respuesta a una pregunta pendiente, el sistema actualmente lo indexa en ChromaDB pero **no intenta automáticamente resolver el pendiente activo**. El usuario debe hacer clic manualmente en "Analizar Fuentes" para que el `DataGapAgent` extraiga el dato, lo que rompe la percepción de inteligencia del sistema.

Esta feature convierte la ingesta de documentos en un disparador automático de resolución de pendientes: al terminar el procesamiento exitoso de un documento (`POST /upload/process/{doc_id}`), el sistema verifica si hay `pending_questions` activas en la sesión, intenta extraer el dato del pendiente activo desde el documento recién indexado usando `DataGapAgent.try_extract_field_from_sources`, y si lo encuentra, lo persiste en `master_profile`, avanza el índice de pendientes y notifica al usuario en la respuesta del endpoint — todo sin bloquear el flujo si no se encuentra el dato.

La infraestructura base ya existe: `_sync_pending_after_analysis` en `upload.py` implementa el mecanismo central. Esta feature formaliza, robustece y extiende ese mecanismo para cubrir todos los casos de borde relevantes.

---

## Glosario

- **AutoResolveHook**: Mecanismo interno (`_sync_pending_after_analysis`) en `upload.py` que se ejecuta al finalizar la indexación de un documento para intentar cerrar el pendiente activo.
- **ChatbotRAGAgent**: Agente conversacional (`backend/app/agents/chatbot_rag.py`) que gestiona el flujo HITL con `pending_questions` y `_apply_saved_pending_value`.
- **DataGapAgent**: Agente (`backend/app/agents/data_gap.py`) que detecta campos faltantes y expone `try_extract_field_from_sources` para buscar un campo específico en el RAG.
- **pending_questions**: Lista de objetos `{field, label, question, document_hint, type}` en `session_state` que representan datos que el sistema necesita del usuario.
- **current_question_index**: Índice entero en `session_state` que apunta al pendiente activo en `pending_questions`.
- **master_profile**: Campo JSON del modelo `Company` donde se persisten los datos estructurados de la empresa.
- **ChromaDB**: Vector store donde se indexan los chunks de texto de los documentos procesados.
- **ANALYZED**: Estado final de un documento tras indexación exitosa en ChromaDB.
- **Pendiente activo**: El elemento de `pending_questions` en la posición `current_question_index`.
- **Resolución automática**: Proceso de extraer un valor del RAG, validarlo, persistirlo en `master_profile` y avanzar `current_question_index` sin intervención del usuario.
- **Tipo `profile`**: Categoría de pendiente que corresponde a datos del perfil de empresa (vs. `economic_price` u otros tipos).

---

## Requisitos

### Requisito 1: Disparo Automático del Hook Post-Ingesta

**User Story:** Como usuario de LicitAI, quiero que al subir un documento el sistema intente automáticamente resolver mi pregunta pendiente activa, para no tener que hacer clic en "Analizar Fuentes" manualmente.

#### Criterios de Aceptación

1. WHEN el endpoint `POST /upload/process/{doc_id}` completa la indexación vectorial exitosa de un documento y marca su estado como `ANALYZED`, THE `AutoResolveHook` SHALL ejecutarse antes de retornar la respuesta al cliente.
2. WHEN el endpoint `POST /upload/process/{doc_id}` recibe un documento ya en estado `ANALYZED` (sin `force=true`), THE `AutoResolveHook` SHALL ejecutarse igualmente para intentar resolver el pendiente activo.
3. WHEN la indexación vectorial falla con error HTTP 4xx o 5xx, THE `AutoResolveHook` SHALL no ejecutarse y el endpoint SHALL retornar el error correspondiente sin intentar resolución.
4. IF el parámetro `company_id` no está presente en la solicitud al endpoint, THEN THE `AutoResolveHook` SHALL retornar inmediatamente con `reason: "missing_company_id"` sin intentar extracción ni modificar el estado de sesión.

---

### Requisito 2: Verificación de Pendientes Activos

**User Story:** Como sistema, quiero verificar si hay pendientes activos antes de intentar extraer datos, para no ejecutar operaciones costosas de RAG innecesariamente.

#### Criterios de Aceptación

1. WHEN el `AutoResolveHook` se ejecuta y `session_state.pending_questions` está vacío o no existe, THE `AutoResolveHook` SHALL retornar con `reason: "no_pending_questions"` sin invocar al `DataGapAgent`.
2. WHEN el `AutoResolveHook` se ejecuta y el pendiente activo tiene `type` distinto de `"profile"`, THE `AutoResolveHook` SHALL retornar con `reason: "current_pending_not_profile"` sin invocar al `DataGapAgent`.
3. WHEN el `AutoResolveHook` se ejecuta y el pendiente activo tiene `field` vacío o nulo, THE `AutoResolveHook` SHALL retornar con `reason: "missing_field_key"` sin invocar al `DataGapAgent`.
4. THE `AutoResolveHook` SHALL calcular el índice del pendiente activo como `max(0, min(current_question_index, len(pending_questions) - 1))` para evitar índices fuera de rango.

---

### Requisito 3: Extracción del Dato desde el Documento Recién Indexado

**User Story:** Como sistema, quiero intentar extraer el dato del pendiente activo desde el documento recién indexado, para resolver automáticamente la pregunta sin intervención del usuario.

#### Criterios de Aceptación

1. WHEN el `AutoResolveHook` determina que hay un pendiente activo de tipo `"profile"`, THE `AutoResolveHook` SHALL invocar `DataGapAgent.try_extract_field_from_sources(session_id, company_id, field_key, correlation_id)` para buscar el valor en el RAG.
2. WHEN `DataGapAgent.try_extract_field_from_sources` retorna un valor, THE `AutoResolveHook` SHALL validar el valor con `DataGapAgent._is_data_valid(field_key, value)` antes de persistirlo.
3. IF `DataGapAgent.try_extract_field_from_sources` retorna `None` o el valor no pasa `_is_data_valid`, THEN THE `AutoResolveHook` SHALL retornar con `reason: "value_not_found_or_invalid"` sin modificar `master_profile` ni `session_state`.
4. THE `DataGapAgent` SHALL buscar el valor primero en la colección corporativa `company_{company_id}` y luego en los documentos de sesión, excluyendo archivos cuyos nombres contengan palabras clave de bases/convocatoria (`bases`, `convocatoria`, `pliego`, `licitacion`, `licitación`, `requisitos`).
5. WHEN el campo a extraer es `cedula_representante`, THE `DataGapAgent` SHALL adicionalmente intentar extracción desde el texto completo (`extracted_text`) de los documentos de sesión usando `_try_extract_cedula_from_session_documents`.

---

### Requisito 4: Persistencia del Dato Resuelto

**User Story:** Como usuario, quiero que el dato extraído automáticamente quede guardado en el perfil de mi empresa, para que no se pierda y no me lo vuelvan a preguntar.

#### Criterios de Aceptación

1. WHEN el `AutoResolveHook` extrae y valida un valor para el pendiente activo, THE `AutoResolveHook` SHALL actualizar `company.master_profile[field_key]` con el valor extraído usando `memory.save_company(company_id, company)`.
2. THE `AutoResolveHook` SHALL obtener el perfil más reciente de la empresa desde la base de datos con `memory.get_company(company_id)` antes de modificarlo, para no sobrescribir datos guardados por otras operaciones concurrentes.
3. THE `AutoResolveHook` SHALL preservar todos los campos existentes de `master_profile` al actualizar un campo individual, sin sobrescribir datos previamente guardados.
4. IF la persistencia en `master_profile` falla por error de base de datos, THEN THE `AutoResolveHook` SHALL retornar con `reason: "persistence_error"` sin avanzar el índice de pendientes ni modificar `session_state`.

---

### Requisito 5: Avance del Índice de Pendientes

**User Story:** Como usuario, quiero que el sistema avance automáticamente a la siguiente pregunta pendiente después de resolver una, para mantener el flujo conversacional sin interrupciones.

#### Criterios de Aceptación

1. WHEN el dato del pendiente activo es persistido exitosamente en `master_profile`, THE `AutoResolveHook` SHALL eliminar el pendiente resuelto de `pending_questions` (por posición, no por índice ciego `+1`) y recalcular `current_question_index` como `max(0, min(idx, len(new_pending) - 1))`.
2. WHEN `pending_questions` queda vacía tras resolver el último pendiente, THE `AutoResolveHook` SHALL establecer `current_question_index` en `0` y `pending_questions` en lista vacía en `session_state`.
3. THE `AutoResolveHook` SHALL persistir el estado actualizado de `pending_questions` y `current_question_index` en `session_state` usando `memory.save_session(session_id, session_state)`.
4. WHEN el `AutoResolveHook` avanza el índice, THE `AutoResolveHook` SHALL incluir en su resultado el `label` y `question` del siguiente pendiente (si existe) para que el endpoint pueda informar al usuario.

---

### Requisito 6: Respuesta Informativa al Usuario

**User Story:** Como usuario, quiero recibir un mensaje claro en la respuesta del endpoint que me indique si el sistema pudo extraer el dato de mi documento, para saber si necesito proporcionar información adicional.

#### Criterios de Aceptación

1. WHEN el `AutoResolveHook` resuelve exitosamente el pendiente activo y existe un siguiente pendiente, THE endpoint SHALL retornar un mensaje con formato: `"He revisado el archivo **{filename}** y ya pude extraer **{field_label}**. ¡Listo! Ahora, para seguir avanzando, necesito: **{next_label}**."`.
2. WHEN el `AutoResolveHook` resuelve exitosamente el pendiente activo y no quedan más pendientes, THE endpoint SHALL retornar un mensaje con formato: `"He revisado el archivo **{filename}** y ya pude extraer **{field_label}**. ¡Listo! Ya no hay pendientes en cola por este bloque."`.
3. WHEN el `AutoResolveHook` no puede extraer el dato del pendiente activo (`reason: "value_not_found_or_invalid"`), THE endpoint SHALL retornar un mensaje con formato: `"Reprocesé el archivo **{filename}**, pero aún no encuentro **{pending_label}** con claridad. ¿Podrías escribírmelo aquí?"`.
4. WHEN el `AutoResolveHook` no se ejecuta por ausencia de pendientes o `company_id`, THE endpoint SHALL retornar el mensaje estándar de confirmación de análisis sin mencionar pendientes.
5. THE endpoint SHALL incluir en el campo `data` de la respuesta el objeto `post_analysis_sync` con los campos: `resolved_current_pending` (bool), `resolved_field` (str|null), `resolved_value` (str|null), `next_pending_label` (str|null), `next_pending_question` (str|null) y `reason` (str).

---

### Requisito 7: No Bloqueo del Flujo Principal

**User Story:** Como usuario, quiero que si el sistema no puede extraer el dato de mi documento, el proceso de subida no falle ni se bloquee, para poder seguir respondiendo por chat.

#### Criterios de Aceptación

1. IF el `AutoResolveHook` lanza una excepción interna no controlada, THEN THE endpoint SHALL capturar la excepción, registrarla en el log con nivel `WARNING` y retornar la respuesta estándar de análisis exitoso sin propagar el error al cliente.
2. WHEN el `AutoResolveHook` retorna `resolved_current_pending: False` por cualquier razón, THE endpoint SHALL retornar `HTTP 200` con `success: True` y el mensaje apropiado según el `reason` devuelto.
3. THE `AutoResolveHook` SHALL completar su ejecución en un tiempo razonable; IF `DataGapAgent.try_extract_field_from_sources` tarda más de 30 segundos, THEN THE `AutoResolveHook` SHALL retornar con `reason: "timeout"` sin bloquear la respuesta al cliente.
4. THE `AutoResolveHook` SHALL ser idempotente: ejecutarlo múltiples veces sobre el mismo documento y sesión SHALL producir el mismo resultado final en `master_profile` y `session_state` (el campo ya guardado no se sobreescribe con un valor diferente si ya es válido).

---

### Requisito 8: Compatibilidad con el Flujo Conversacional Existente

**User Story:** Como desarrollador, quiero que la resolución automática vía upload sea transparente para el `ChatbotRAGAgent`, para que el flujo conversacional continúe correctamente sin importar cómo se resolvió el pendiente.

#### Criterios de Aceptación

1. WHEN el `AutoResolveHook` resuelve un pendiente y avanza `current_question_index`, THE `ChatbotRAGAgent` SHALL detectar en el siguiente turno conversacional que el pendiente ya fue resuelto (porque ya no está en `pending_questions`) y formular directamente la siguiente pregunta sin intentar guardar el dato resuelto de nuevo.
2. THE `AutoResolveHook` SHALL usar la misma lógica de eliminación de pendientes que `ChatbotRAGAgent._apply_saved_pending_value`: eliminar por posición (`pending[:idx] + pending[idx+1:]`) y recalcular índice con `max(0, min(idx, len(new_pending) - 1))`.
3. THE `AutoResolveHook` SHALL actualizar `session_state` de forma atómica: leer el estado más reciente con `memory.get_session`, aplicar cambios y guardar con `memory.save_session` en una sola operación por ejecución del hook.
4. WHEN el `AutoResolveHook` resuelve un pendiente de tipo `economic_price`, THE `AutoResolveHook` SHALL no intentar persistirlo en `master_profile` y SHALL retornar con `reason: "current_pending_not_profile"` (los precios se gestionan exclusivamente por el `ChatbotRAGAgent` vía `_save_price_to_catalog`).
5. THE `AutoResolveHook` SHALL registrar en el log de auditoría cada resolución exitosa con el formato: `[AutoResolve] ✅ Resuelto '{field_key}' = '{value[:40]}' para sesión {session_id}`.

