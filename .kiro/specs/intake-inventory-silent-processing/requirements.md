# Documento de Requisitos

## Introducción

El `IntakePlannerAgent` genera tres tipos de pendientes conversacionales para guiar al usuario durante el proceso de intake de una licitación. Los pendientes de tipo `INTAKE-INV-*` (`question_type="I"`) representan inventarios de documentos pendientes agrupados por categoría (legal_administrativa, técnica, económica). Actualmente estos pendientes llegan a la cola conversacional del `ChatbotRAGAgent` sin un handler específico, lo que provoca que el LLM genérico los procese de forma incorrecta: inventa respuestas, no sabe qué hacer con la respuesta del usuario, y genera una experiencia de usuario confusa.

Este feature elimina los `INTAKE-INV-*` del flujo conversacional procesándolos silenciosamente: el análisis de inventario sigue ejecutándose y su resultado (`table_data`) sigue disponible para la UI, pero estas preguntas nunca llegan al chat. Los pendientes `INTAKE-B-*` y `INTAKE-Q-*` no se modifican.

## Glosario

- **IntakePlannerAgent**: Agente que consolida hallazgos multiagente en una lista priorizada de preguntas de intake.
- **ChatbotRAGAgent**: Agente conversacional que gestiona la cola de `pending_questions` y responde al usuario.
- **INTAKE-INV-***: Pendientes de inventario documental con `question_type="I"`, generados por `_questions_from_inventory`. Representan grupos de documentos pendientes por categoría.
- **INTAKE-B-***: Pendientes bloqueantes de datos (`question_type="B"`). No se modifican.
- **INTAKE-Q-***: Pendientes de clasificación/calidad (`question_type="Q"`). No se modifican.
- **intake_plan**: Diccionario almacenado en `session_state` con la clave `intake_plan`, que contiene el campo `questions` (lista de pendientes) y `summary`.
- **pending_questions**: Lista en `session_state` con los pendientes activos que el chatbot formula al usuario secuencialmente.
- **inventory_summary**: Campo nuevo propuesto en el `intake_plan` para almacenar los datos de inventario sin incluirlos en `questions`.
- **table_data**: Campo Markdown dentro de cada pendiente `INTAKE-INV-*` que contiene la tabla de documentos pendientes por categoría.
- **Sanitize**: Proceso de limpieza de `pending_questions` que descarta pendientes inválidos u obsoletos antes de presentarlos al usuario.
- **Panel de Estado de Intake**: Sección de la UI que muestra el estado del inventario documental (ya existe en el frontend).
- **question_type**: Campo que identifica el tipo de pendiente: `"I"` (inventario), `"B"` (bloqueante), `"Q"` (calidad), `"A"` (análisis).

---

## Requisitos

### Requisito 1: Separación del inventario del flujo conversacional

**User Story:** Como usuario de LicitAI, quiero que el chatbot no me haga preguntas confusas sobre inventarios de documentos, para que la conversación sea clara y accionable.

#### Criterios de Aceptación

1. CUANDO el `IntakePlannerAgent` genera pendientes con `question_type="I"`, EL `IntakePlannerAgent` NO SHALL incluirlos en el campo `questions` del `intake_plan`.
2. EL `IntakePlannerAgent` SHALL almacenar los datos de inventario documental en un campo separado `inventory_summary` dentro del `intake_plan`, preservando el `table_data` de cada categoría.
3. CUANDO el `intake_plan` se construye, EL `IntakePlannerAgent` SHALL incluir en `inventory_summary` al menos los campos: `category`, `count`, `table_data`, `priority` y `field_target` por cada grupo de inventario.
4. EL `IntakePlannerAgent` SHALL continuar ejecutando el análisis de inventario documental completo independientemente de si hay documentos pendientes o no.

### Requisito 2: Filtrado defensivo en el ChatbotRAGAgent

**User Story:** Como desarrollador de LicitAI, quiero que el chatbot filtre silenciosamente cualquier pendiente de inventario que llegue a la cola conversacional, para proteger la experiencia de usuario ante sesiones antiguas o datos inconsistentes.

#### Criterios de Aceptación

1. CUANDO `_sanitize_economic_pending_questions` procesa la lista `pending_questions`, EL `ChatbotRAGAgent` SHALL descartar silenciosamente todo pendiente cuyo `question_type` sea `"I"`.
2. CUANDO `_sanitize_economic_pending_questions` procesa la lista `pending_questions`, EL `ChatbotRAGAgent` SHALL descartar silenciosamente todo pendiente cuyo `field_target` comience con el prefijo `"inventory."`.
3. CUANDO se descartan pendientes de inventario durante el sanitize, EL `ChatbotRAGAgent` SHALL registrar un log de nivel `INFO` con el `question_id` y la razón del descarte.
4. EL `ChatbotRAGAgent` SHALL preservar sin modificación todos los pendientes con `question_type` distinto de `"I"` y con `field_target` que no comience con `"inventory."`.
5. IF el `pending_questions` de una sesión existente contiene pendientes `INTAKE-INV-*` (sesiones creadas antes del deploy), THEN EL `ChatbotRAGAgent` SHALL limpiarlos en el primer ciclo de sanitize sin requerir intervención manual.

### Requisito 3: Disponibilidad del inventario para la UI

**User Story:** Como usuario de LicitAI, quiero ver el inventario de documentos pendientes en el panel de estado de la UI, para saber qué documentos debo preparar sin que el chatbot me lo pregunte.

#### Criterios de Aceptación

1. EL `IntakePlannerAgent` SHALL incluir el campo `inventory_summary` en el `AgentOutput.data` cuando existan documentos pendientes en el inventario.
2. CUANDO no existen documentos pendientes en el inventario, EL `IntakePlannerAgent` SHALL incluir `inventory_summary` como lista vacía `[]` en el `AgentOutput.data`.
3. EL `intake_plan` almacenado en `session_state` SHALL contener el campo `inventory_summary` con los mismos datos que el `AgentOutput.data`.
4. WHERE el frontend consume el `intake_plan`, EL `Panel de Estado de Intake` SHALL poder leer `inventory_summary` para renderizar el inventario documental sin depender del flujo conversacional.

### Requisito 4: Preservación de invariantes del sistema

**User Story:** Como desarrollador de LicitAI, quiero que el cambio no rompa ningún flujo existente, para garantizar la estabilidad del sistema en producción.

#### Criterios de Aceptación

1. EL `IntakePlannerAgent` SHALL continuar generando pendientes `INTAKE-B-*` y `INTAKE-Q-*` en el campo `questions` del `intake_plan` sin ninguna modificación.
2. CUANDO el `ChatbotRAGAgent` procesa pendientes `INTAKE-B-*` o `INTAKE-Q-*`, EL `ChatbotRAGAgent` SHALL mantener el comportamiento actual sin cambios.
3. EL `IntakePlannerAgent` SHALL continuar generando el campo `table_data` con la tabla Markdown de documentos para cada grupo de inventario.
4. CUANDO `INTAKE_PLANNER_ENABLED` es `False` en `Settings`, EL sistema SHALL comportarse exactamente igual que antes de este feature (sin inyección de inventario).
5. EL `ChatbotRAGAgent` SHALL mantener el campo `table_data` en los pendientes `INTAKE-B-*` e `INTAKE-Q-*` si estos lo contienen, sin descartarlo.

### Requisito 5: Resumen de inventario en el `summary` del plan

**User Story:** Como desarrollador de LicitAI, quiero que el `summary` del `intake_plan` refleje correctamente los conteos de pendientes excluyendo los de inventario, para que las métricas del plan sean precisas.

#### Criterios de Aceptación

1. CUANDO el `IntakePlannerAgent` calcula el `summary` del plan, EL `IntakePlannerAgent` SHALL excluir los pendientes de inventario (`question_type="I"`) del conteo de `blocking_count`, `critical_count`, `important_count` y `complementary_count`.
2. EL `IntakePlannerAgent` SHALL incluir en el `summary` un campo `inventory_pending_count` con el número total de documentos pendientes en el inventario (suma de todos los grupos).
3. CUANDO no hay documentos pendientes en el inventario, EL `IntakePlannerAgent` SHALL establecer `inventory_pending_count` en `0`.
