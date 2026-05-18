# Documento de Requisitos

## Introducción

La feature **Recolección Inteligente de Datos vía Chatbot** extiende el flujo conversacional existente de LicitAI para guiar al usuario de forma proactiva y estructurada en la resolución de todas las brechas de datos detectadas por el `GoNoGoAgent` y el `DataGapAgent`. El chatbot convierte las brechas en preguntas conversacionales, acepta respuestas directas o documentos como fuente, persiste cada dato capturado en el `master_profile` de la empresa, recalcula el semáforo Go/No-Go tras cada captura y notifica al usuario cuando el expediente está completo para proceder a generar la propuesta.

El flujo se integra sobre la infraestructura existente: `ChatbotRAGAgent`, `DataGapAgent`, `GoNoGoAgent`, el endpoint `POST /companies/` y el campo `session_state.pending_questions`.

---

## Glosario

- **ChatbotRAG**: Agente conversacional existente (`backend/app/agents/chatbot_rag.py`) que opera en modos QUERY, DATA_INTAKE y PENDING.
- **DataGapAgent**: Agente (`backend/app/agents/data_gap.py`) que detecta campos faltantes en el `master_profile` y genera la lista `pending_questions`.
- **GoNoGoAgent**: Agente (`backend/app/agents/go_no_go.py`) que calcula brechas y el estado del semáforo (RED / YELLOW / GREEN).
- **Semáforo**: Estado de cumplimiento de la empresa frente a los requisitos de la licitación: RED (knock-outs), YELLOW (brechas sin knock-out), GREEN (sin brechas).
- **master_profile**: Campo JSON del modelo `Company` donde se persisten los datos estructurados de la empresa.
- **pending_questions**: Lista de objetos `{field, label, question, document_hint}` almacenada en `session_state` por el `DataGapAgent`.
- **Brecha**: Dato o requisito que la empresa no puede acreditar con la información disponible en su `master_profile`.
- **Fuente de Verdad**: Documento indexado en el vector store de la sesión del que el sistema puede extraer datos automáticamente.
- **Modo DATA_INTAKE**: Modo del `ChatbotRAG` en el que el usuario proporciona un dato directamente en el chat.
- **Modo PENDING**: Modo del `ChatbotRAG` en el que el agente formula proactivamente la siguiente pregunta pendiente.
- **Recálculo de Semáforo**: Invocación al endpoint `POST /go-no-go/{session_id}/authorize` con `recalculate_only: true` para actualizar el estado del semáforo sin reanudar el pipeline.

---

## Requisitos

### Requisito 1: Inicio Proactivo del Flujo de Recolección

**User Story:** Como usuario de LicitAI, quiero que el chatbot me indique automáticamente qué datos faltan al iniciar una conversación, para no tener que buscar manualmente qué información necesito proporcionar.

#### Criterios de Aceptación

1. WHEN el usuario envía un mensaje de saludo o una consulta vacía y existe al menos una `pending_question` en `session_state`, THE `ChatbotRAG` SHALL responder con la primera pregunta pendiente sin esperar instrucción explícita del usuario.
2. WHEN el usuario envía un mensaje de saludo o una consulta vacía y no existen `pending_questions` en `session_state`, THE `ChatbotRAG` SHALL invocar al `DataGapAgent` para detectar brechas antes de responder.
3. WHEN el `DataGapAgent` detecta brechas nuevas durante la invocación proactiva, THE `ChatbotRAG` SHALL presentar la primera pregunta pendiente en la misma respuesta al usuario.
4. IF el `DataGapAgent` no puede conectarse a la base de datos durante la invocación proactiva, THEN THE `ChatbotRAG` SHALL responder con un mensaje de bienvenida genérico sin bloquear la conversación.

---

### Requisito 2: Formulación Conversacional de Preguntas

**User Story:** Como usuario, quiero que el chatbot me haga preguntas claras y contextualizadas sobre los datos faltantes, para entender exactamente qué información necesito proporcionar y de qué documento puedo obtenerla.

#### Criterios de Aceptación

1. THE `ChatbotRAG` SHALL formular cada pregunta pendiente usando el texto definido en el campo `question` del objeto `pending_question`, interpolando el nombre de la empresa (`razon_social`) cuando corresponda.
2. WHEN el `ChatbotRAG` formula una pregunta pendiente, THE `ChatbotRAG` SHALL incluir en el mensaje el `document_hint` del campo correspondiente como sugerencia de fuente documental.
3. THE `ChatbotRAG` SHALL presentar las preguntas de forma secuencial, una por turno, avanzando a la siguiente solo después de que el dato anterior haya sido guardado exitosamente.
4. WHEN el usuario solicita ver todos los datos pendientes (intención de aclaración detectada por `_evaluate_clarification_intent`), THE `ChatbotRAG` SHALL listar todas las `pending_questions` restantes con su etiqueta y pregunta completa.
5. THE `ChatbotRAG` SHALL mantener el tono conversacional en todas las respuestas, evitando presentar los datos faltantes como un formulario o lista de campos técnicos.

---

### Requisito 3: Captura de Datos Escritos Directamente en el Chat

**User Story:** Como usuario, quiero poder escribir el dato solicitado directamente en el chat, para que el sistema lo guarde sin necesidad de navegar a otra pantalla.

#### Criterios de Aceptación

1. WHEN el usuario envía un mensaje clasificado como `DATA_INTAKE` y existe una `pending_question` activa, THE `ChatbotRAG` SHALL extraer el valor del dato usando el LLM y guardarlo en el `master_profile` de la empresa.
2. WHEN el valor extraído del mensaje del usuario es `AMBIGUO`, THE `ChatbotRAG` SHALL solicitar al usuario que reformule su respuesta indicando el campo específico que se espera.
3. WHEN el dato es guardado exitosamente en el `master_profile`, THE `ChatbotRAG` SHALL confirmar al usuario el campo guardado y el valor capturado antes de formular la siguiente pregunta.
4. THE `ChatbotRAG` SHALL persistir el dato capturado invocando `_save_field_to_company` que actualiza el `master_profile` vía `MCPContextManager.memory.save_company`.
5. IF la persistencia del dato falla por error de base de datos, THEN THE `ChatbotRAG` SHALL notificar al usuario que el dato no pudo guardarse y solicitar que lo intente de nuevo.
6. WHEN el dato capturado corresponde a un precio unitario (tipo `economic_price`), THE `ChatbotRAG` SHALL persistirlo en el catálogo de la empresa (`company.catalog`) en lugar del `master_profile`.

---

### Requisito 4: Captura de Datos vía Documento Subido

**User Story:** Como usuario, quiero poder subir un documento como fuente de un dato faltante, para que el sistema extraiga automáticamente la información sin que yo tenga que escribirla manualmente.

#### Criterios de Aceptación

1. WHEN el usuario indica que subirá o ya subió un documento como respuesta a una pregunta pendiente, THE `ChatbotRAG` SHALL recordar al usuario que debe hacer clic en "Analizar Fuentes" para que el sistema indexe el documento y extraiga el dato automáticamente.
2. WHEN el usuario hace clic en "Analizar Fuentes" y el `DataGapAgent` logra extraer el dato faltante desde el documento indexado, THE `DataGapAgent` SHALL persistir el valor en el `master_profile` y eliminar la pregunta correspondiente de `pending_questions`.
3. WHEN el `DataGapAgent` no puede extraer el dato del documento indexado, THE `DataGapAgent` SHALL mantener la pregunta en `pending_questions` para que el `ChatbotRAG` la vuelva a formular al usuario.
4. THE `DataGapAgent` SHALL excluir documentos cuyo nombre contenga palabras clave de bases/convocatoria (`bases`, `convocatoria`, `pliego`, `licitacion`) al buscar datos del oferente en el vector store de la sesión.

---

### Requisito 5: Persistencia en el Perfil Maestro

**User Story:** Como usuario, quiero que cada dato que proporciono quede guardado permanentemente en el perfil de mi empresa, para no tener que volver a ingresarlo en futuras licitaciones.

#### Criterios de Aceptación

1. WHEN un dato es capturado por el `ChatbotRAG` vía `DATA_INTAKE`, THE `ChatbotRAG` SHALL actualizar el campo correspondiente en `company.master_profile` usando el endpoint existente de companies (`POST /companies/`).
2. THE `ChatbotRAG` SHALL preservar todos los campos existentes del `master_profile` al actualizar un campo individual, sin sobrescribir datos previamente guardados.
3. WHEN el `DataGapAgent` auto-extrae un dato desde el RAG, THE `DataGapAgent` SHALL persistir el valor en `company.master_profile` invocando `_persist_profile_updates`.
4. THE `DataGapAgent` SHALL obtener siempre el perfil más reciente desde la base de datos antes de evaluar brechas, ignorando el `company_data` del `agent_input` para evitar datos obsoletos del frontend.
5. IF el `company_id` no está disponible en el contexto de la sesión, THEN THE `ChatbotRAG` SHALL solicitar al usuario que seleccione su empresa antes de intentar guardar cualquier dato.

---

### Requisito 6: Recálculo del Semáforo Go/No-Go

**User Story:** Como usuario, quiero ver el semáforo Go/No-Go actualizarse después de cada dato que proporciono, para saber en tiempo real cómo progresa mi expediente hacia el cumplimiento de los requisitos.

#### Criterios de Aceptación

1. WHEN un dato es guardado exitosamente en el `master_profile` por el `ChatbotRAG`, THE sistema SHALL invocar el endpoint `POST /go-no-go/{session_id}/authorize` con `recalculate_only: true` para actualizar el semáforo.
2. WHEN el recálculo del semáforo retorna un nuevo `go_no_go_result`, THE sistema SHALL persistir el resultado en `session_state.go_no_go_result` para que el `GoNoGoPanel` del frontend lo refleje.
3. WHEN el semáforo cambia de estado (ej: de YELLOW a GREEN) tras guardar un dato, THE `ChatbotRAG` SHALL incluir en su respuesta una notificación del cambio de estado del semáforo.
4. IF el recálculo del semáforo falla por error interno, THEN THE sistema SHALL continuar el flujo conversacional sin interrumpir al usuario, registrando el error en el log.
5. WHILE el recálculo del semáforo está en progreso, THE `GoNoGoPanel` SHALL mostrar el indicador "⏳ Recalculando semáforo…" al usuario.

---

### Requisito 7: Progresión Secuencial y Finalización del Flujo

**User Story:** Como usuario, quiero que el chatbot avance automáticamente a la siguiente pregunta pendiente después de cada respuesta, y me notifique cuando haya completado todos los datos necesarios para generar la propuesta.

#### Criterios de Aceptación

1. WHEN un dato es guardado exitosamente, THE `ChatbotRAG` SHALL incrementar `session_state.current_question_index` y formular la siguiente `pending_question` en la misma respuesta de confirmación.
2. WHEN `current_question_index` alcanza el total de `pending_questions`, THE `ChatbotRAG` SHALL limpiar `pending_questions` y `current_question_index` en `session_state` y notificar al usuario que el expediente está completo.
3. WHEN todas las `pending_questions` han sido resueltas y el semáforo es GREEN, THE `ChatbotRAG` SHALL indicar al usuario que puede proceder a generar la propuesta técnica y económica.
4. WHEN el usuario decide continuar con brechas restantes sin resolver todas las preguntas, THE `ChatbotRAG` SHALL respetar la decisión y no bloquear el flujo conversacional.
5. THE `ChatbotRAG` SHALL permitir al usuario responder preguntas fuera de orden si el usuario lo solicita explícitamente, actualizando `current_question_index` al campo correspondiente.

---

### Requisito 8: Compatibilidad con el Pipeline Existente

**User Story:** Como desarrollador, quiero que la feature de recolección de datos no rompa ningún flujo existente del pipeline de LicitAI, para garantizar la estabilidad del sistema en producción.

#### Criterios de Aceptación

1. THE `ChatbotRAG` SHALL mantener los modos QUERY, DATA_INTAKE, META y PENDING existentes sin modificar su lógica de clasificación de mensajes.
2. WHEN el `ChatbotRAG` opera en modo QUERY (el usuario pregunta sobre las bases), THE `ChatbotRAG` SHALL responder con el flujo RAG estándar independientemente de si existen `pending_questions`.
3. THE `DataGapAgent` SHALL continuar funcionando como agente independiente invocable desde el orquestador, sin depender del `ChatbotRAG` para su ejecución.
4. THE endpoint `POST /go-no-go/{session_id}/authorize` con `recalculate_only: true` SHALL ser el único mecanismo de recálculo del semáforo, sin duplicar lógica de scoring.
5. WHEN el `ChatbotRAG` guarda un dato en el `master_profile`, THE `ChatbotRAG` SHALL usar exclusivamente `MCPContextManager.memory.save_company` para garantizar consistencia con el resto del pipeline.
6. THE sistema SHALL preservar el campo `session_state.pending_questions` como la única fuente de verdad del estado de recolección de datos, evitando duplicar este estado en otras estructuras.
