# Plan de Implementación: intake-inventory-silent-processing

## Visión General

Dos cambios quirúrgicos en Python para eliminar los pendientes `INTAKE-INV-*` del flujo conversacional:
1. `IntakePlannerAgent`: mover el inventario de `questions` a `inventory_summary`.
2. `ChatbotRAGAgent._sanitize_economic_pending_questions`: agregar filtro defensivo de inventario.

## Tareas

- [x] 1. Refactorizar `IntakePlannerAgent._questions_from_inventory` para retornar `inventory_summary`
  - Renombrar el método a `_inventory_summary_from_inventory` en `backend/app/agents/intake_planner.py`
  - Cambiar el tipo de retorno: eliminar los campos conversacionales (`question`, `required_evidence`, `question_type`, `type`) y conservar `category`, `count`, `priority`, `blocking`, `field_target`, `table_data`, `provenance_ui`
  - El método debe retornar `List[Dict[str, Any]]` con un elemento por categoría que tenga ítems pendientes
  - Preservar la lógica de agrupación por categoría y construcción de `table_data` sin cambios
  - _Requisitos: 1.1, 1.2, 1.3, 1.4_

  - [x]* 1.1 Escribir test de propiedad: `questions` nunca contiene pendientes de inventario
    - **Propiedad 1: El campo `questions` nunca contiene pendientes de inventario**
    - Usar Hypothesis para generar `session_state` con `document_inventory` aleatorio (0 a 30 ítems, categorías aleatorias, status aleatorio)
    - Verificar que `data["questions"]` no contiene ningún elemento con `question_type="I"` ni `field_target` con prefijo `"inventory."`
    - Archivo: `backend/tests/test_intake_inventory_silent.py`
    - Tag: `# Feature: intake-inventory-silent-processing, Property 1: questions nunca contiene pendientes de inventario`
    - **Valida: Requisitos 1.1, 4.1**

  - [x]* 1.2 Escribir test de propiedad: `inventory_summary` contiene todos los grupos con estructura completa
    - **Propiedad 2: `inventory_summary` contiene todos los grupos de inventario con estructura completa**
    - Usar Hypothesis para generar inventarios con N categorías (1 a 3) y M ítems pendientes por categoría
    - Verificar que `inventory_summary` tiene exactamente N elementos y cada uno contiene `category`, `count`, `priority`, `field_target`, `table_data`
    - Tag: `# Feature: intake-inventory-silent-processing, Property 2: inventory_summary contiene todos los grupos con estructura completa`
    - **Valida: Requisitos 1.2, 1.3, 3.1**

- [x] 2. Extender `_summary()` para incluir `inventory_pending_count` y excluir inventario de conteos
  - Modificar la firma de `_summary` en `backend/app/agents/intake_planner.py` para aceptar `inventory_summary: Optional[List[Dict[str, Any]]] = None`
  - Calcular `inventory_pending_count = sum(int(item.get("count") or 0) for item in (inventory_summary or []))`
  - Agregar `"inventory_pending_count": inventory_pending_count` al dict de retorno
  - Verificar que los conteos `blocking_count`, `critical_count`, etc. solo cuentan elementos de `questions` (ya es así, pero confirmar que no hay `question_type="I"` en `questions` antes de llamar a `_summary`)
  - _Requisitos: 5.1, 5.2, 5.3_

  - [x]* 2.1 Escribir test de propiedad: `inventory_pending_count` es la suma de los `count` de `inventory_summary`
    - **Propiedad 5: `summary.inventory_pending_count` es la suma de los `count` de `inventory_summary`**
    - Usar Hypothesis para generar listas de `inventory_summary` con counts aleatorios (0 a 20 por elemento)
    - Verificar que `summary["inventory_pending_count"] == sum(item["count"] for item in inventory_summary)`
    - Tag: `# Feature: intake-inventory-silent-processing, Property 5: inventory_pending_count es la suma de los count de inventory_summary`
    - **Valida: Requisitos 5.1, 5.2**

  - [x]* 2.2 Escribir test de propiedad: los conteos del `summary` excluyen los pendientes de inventario
    - **Propiedad 6: Los conteos del `summary` excluyen los pendientes de inventario**
    - Usar Hypothesis para generar `session_state` completo con inventario y pendientes B/Q/A
    - Verificar que `blocking_count + critical_count + important_count + complementary_count == len(questions)`
    - Tag: `# Feature: intake-inventory-silent-processing, Property 6: los conteos del summary excluyen los pendientes de inventario`
    - **Valida: Requisito 5.1**

- [x] 3. Actualizar `IntakePlannerAgent.process()` para usar el nuevo campo `inventory_summary`
  - En `backend/app/agents/intake_planner.py`, en el método `process()`:
    - Reemplazar la llamada `questions.extend(self._questions_from_inventory(session_state))` por `inventory_summary = self._inventory_summary_from_inventory(session_state)`
    - Pasar `inventory_summary` a `self._summary(questions, inventory_summary)`
    - Agregar `"inventory_summary": inventory_summary` al dict `data`
    - Actualizar `"plan_version"` a `"1.2.0"`
  - _Requisitos: 1.1, 1.2, 3.1, 3.2, 3.3_

- [x] 4. Checkpoint — Verificar que los tests del IntakePlannerAgent pasan
  - Asegurarse de que todos los tests pasan, preguntar al usuario si surgen dudas.

- [x] 5. Agregar filtro defensivo de inventario en `ChatbotRAGAgent._sanitize_economic_pending_questions`
  - En `backend/app/agents/chatbot_rag.py`, al inicio del método `_sanitize_economic_pending_questions`, antes del bloque de verificación de snapshot económico:
    - Iterar sobre `pending` y descartar elementos donde `question_type == "I"` o `field_target.startswith("inventory.")`
    - Emitir `logger.info("chatbot_inventory_pending_discarded", session_id=session_id, question_id=..., reason="inventory_silent_processing")` por cada descarte
    - Reasignar `pending = inventory_filtered` antes de continuar con la lógica existente
  - Verificar que el campo `question_type` se lee de `q.get("question_type") or q.get("type")` para compatibilidad con el formato legacy (donde el campo se llama `type`)
  - _Requisitos: 2.1, 2.2, 2.3, 2.5_

  - [x]* 5.1 Escribir test de propiedad: el sanitize elimina todos los pendientes de inventario
    - **Propiedad 3: El sanitize elimina todos los pendientes de inventario**
    - Usar Hypothesis para generar listas `pending_questions` con mezcla aleatoria de tipos (`"I"`, `"B"`, `"Q"`, `"economic_price"`, `"profile_field"`) y `field_target` con y sin prefijo `"inventory."`
    - Verificar que el resultado no contiene ningún elemento con `question_type="I"` ni `field_target` con prefijo `"inventory."`
    - Archivo: `backend/tests/test_intake_inventory_silent.py`
    - Tag: `# Feature: intake-inventory-silent-processing, Property 3: el sanitize elimina todos los pendientes de inventario`
    - **Valida: Requisitos 2.1, 2.2, 2.5**

  - [x]* 5.2 Escribir test de propiedad: el sanitize preserva los pendientes no-inventario
    - **Propiedad 4: El sanitize preserva los pendientes no-inventario**
    - Usar Hypothesis para generar listas de pendientes con tipos no-inventario (`"B"`, `"Q"`, `"economic_price"`, `"profile_field"`, `"intake_planner"`)
    - Verificar que el resultado contiene exactamente los mismos elementos (mismos campos, mismo orden relativo)
    - Tag: `# Feature: intake-inventory-silent-processing, Property 4: el sanitize preserva los pendientes no-inventario`
    - **Valida: Requisitos 2.4, 4.1, 4.2**

- [x] 6. Checkpoint final — Verificar que todos los tests pasan
  - Ejecutar `pytest backend/tests/test_intake_inventory_silent.py -v` y verificar que todos los tests pasan
  - Ejecutar `pytest backend/tests/test_economic_sync.py -v` para verificar no-regresión en el sanitize económico
  - Asegurarse de que todos los tests pasan, preguntar al usuario si surgen dudas.

## Notas

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- El filtro en `_sanitize_economic_pending_questions` debe leer tanto `question_type` como `type` para compatibilidad con el formato legacy de pendientes (donde el campo se llama `type` en lugar de `question_type`)
- El campo `inventory_summary` es aditivo: el frontend puede ignorarlo si no lo implementa aún
- No se requieren migraciones de base de datos: todos los cambios son en memoria/session_state
- Los tests de propiedad usan Hypothesis, que ya está instalado en el proyecto (ver `.hypothesis/` en la raíz)
