# Documento de Diseño: intake-inventory-silent-processing

## Visión General

El `IntakePlannerAgent` genera actualmente tres tipos de pendientes conversacionales. Los de tipo `INTAKE-INV-*` (`question_type="I"`) representan inventarios de documentos agrupados por categoría. El problema es que estos pendientes llegan a la cola conversacional del `ChatbotRAGAgent` sin un handler específico, lo que provoca que el LLM genérico los procese incorrectamente.

Este diseño describe dos cambios quirúrgicos y complementarios:

1. **En `IntakePlannerAgent`**: mover los pendientes `INTAKE-INV-*` fuera del campo `questions` hacia un campo nuevo `inventory_summary`, de modo que nunca entren a la cola conversacional.
2. **En `ChatbotRAGAgent._sanitize_economic_pending_questions`**: agregar un filtro defensivo que descarte silenciosamente cualquier pendiente con `question_type="I"` o `field_target` con prefijo `"inventory."`, protegiendo sesiones antiguas.

Los pendientes `INTAKE-B-*` y `INTAKE-Q-*` no se tocan en ningún punto.

---

## Arquitectura

```
IntakePlannerAgent.process()
  ├── _questions_from_quality_hints()  → questions[] (Q)
  ├── _questions_from_inventory()      → inventory_summary[] (I) ← NUEVO: campo separado
  ├── _questions_from_go_no_go()       → questions[] (B)
  ├── _questions_from_analysis()       → questions[] (B)
  └── _questions_from_pending()        → questions[] (A)

AgentOutput.data = {
  "plan_version": "1.2.0",
  "summary": {
    "blocking_count": N,       ← excluye los I
    "critical_count": N,
    "important_count": N,
    "complementary_count": N,
    "inventory_pending_count": M   ← NUEVO
  },
  "questions": [...B, ...Q, ...A],   ← sin ningún I
  "inventory_summary": [             ← NUEVO
    {
      "category": "legal_administrative",
      "count": 7,
      "priority": "BLOQUEANTE",
      "field_target": "inventory.legal_administrative.completion",
      "table_data": "| Anexo | ... |"
    },
    ...
  ]
}
```

```
ChatbotRAGAgent._sanitize_economic_pending_questions()
  ├── [existente] filtro economic_price huérfanas
  ├── [existente] filtro obra pública
  └── [NUEVO] filtro inventory: question_type="I" o field_target.startswith("inventory.")
```

---

## Componentes e Interfaces

### `IntakePlannerAgent` (backend/app/agents/intake_planner.py)

#### Cambio 1: `_questions_from_inventory` → retorna `inventory_summary`

El método `_questions_from_inventory` actualmente retorna una lista de dicts con `question_type="I"` que se mezclan en `questions`. El cambio es:

- Renombrar el método a `_inventory_summary_from_inventory` (o mantener el nombre y cambiar el contrato de retorno).
- El método retorna la misma estructura de datos pero sin los campos conversacionales (`question`, `required_evidence`). Retorna una lista de dicts con: `category`, `count`, `priority`, `blocking`, `field_target`, `table_data`, `provenance_ui`.
- El campo `question_type` se elimina del output (ya no es necesario porque no va a `questions`).

#### Cambio 2: `process()` — separar inventory de questions

```python
async def process(self, agent_input: AgentInput) -> AgentOutput:
    ...
    questions = []
    questions.extend(self._questions_from_quality_hints(session_state))
    # YA NO: questions.extend(self._questions_from_inventory(session_state))
    questions.extend(self._questions_from_go_no_go(gng))
    questions.extend(self._questions_from_analysis(analysis))
    questions.extend(self._questions_from_pending(pending))
    questions = self._sort_questions(self._dedupe(questions))

    # NUEVO: inventario en campo separado
    inventory_summary = self._inventory_summary_from_inventory(session_state)

    data = {
        "plan_version": "1.2.0",
        "summary": self._summary(questions, inventory_summary),  # firma extendida
        "questions": questions,
        "inventory_summary": inventory_summary,
    }
    ...
```

#### Cambio 3: `_summary()` — extender firma

```python
def _summary(
    self,
    questions: List[Dict[str, Any]],
    inventory_summary: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, int]:
    counts = {"BLOQUEANTE": 0, "CRITICO": 0, "IMPORTANTE": 0, "COMPLEMENTARIO": 0}
    for q in questions:
        p = str(q.get("priority") or "").upper()
        if p in counts:
            counts[p] += 1
    inventory_pending_count = sum(
        int(item.get("count") or 0) for item in (inventory_summary or [])
    )
    return {
        "blocking_count": counts["BLOQUEANTE"],
        "critical_count": counts["CRITICO"],
        "important_count": counts["IMPORTANTE"],
        "complementary_count": counts["COMPLEMENTARIO"],
        "inventory_pending_count": inventory_pending_count,
    }
```

### `ChatbotRAGAgent` (backend/app/agents/chatbot_rag.py)

#### Cambio 4: `_sanitize_economic_pending_questions` — filtro defensivo

Al inicio del método, antes de cualquier otra lógica, agregar:

```python
# Filtro defensivo: descartar pendientes de inventario documental.
# Estos nunca deben llegar al flujo conversacional (question_type="I"
# o field_target con prefijo "inventory.").
inventory_filtered: List[Dict[str, Any]] = []
for q in pending:
    q_type = str(q.get("question_type") or q.get("type") or "")
    field_target = str(q.get("field_target") or q.get("field") or "")
    if q_type == "I" or field_target.startswith("inventory."):
        logger.info(
            "chatbot_inventory_pending_discarded",
            session_id=session_id,
            question_id=str(q.get("question_id") or ""),
            reason="inventory_silent_processing",
        )
        continue
    inventory_filtered.append(q)
pending = inventory_filtered
```

Este bloque se inserta **antes** del bloque de verificación de snapshot económico, para que la lista `pending` ya esté limpia cuando se evalúen las condiciones económicas.

---

## Modelos de Datos

### `inventory_summary` (nuevo campo en `intake_plan`)

```python
# Tipo: List[Dict[str, Any]]
# Cada elemento representa un grupo de documentos pendientes por categoría.
{
    "category": str,          # "legal_administrative" | "technical" | "economic"
    "count": int,             # número de documentos pendientes en esta categoría
    "priority": str,          # "BLOQUEANTE" | "CRITICO"
    "blocking": bool,         # True si category == "legal_administrative"
    "field_target": str,      # "inventory.{category}.completion"
    "table_data": str,        # tabla Markdown con los documentos pendientes
    "provenance_ui": dict,    # {"source": "document_inventory", "confidence": 0.9, ...}
}
```

### `summary` (campo extendido en `intake_plan`)

```python
{
    "blocking_count": int,           # pendientes BLOQUEANTE (excluye inventario)
    "critical_count": int,           # pendientes CRITICO (excluye inventario)
    "important_count": int,          # pendientes IMPORTANTE (excluye inventario)
    "complementary_count": int,      # pendientes COMPLEMENTARIO (excluye inventario)
    "inventory_pending_count": int,  # NUEVO: total de documentos pendientes en inventario
}
```

### Compatibilidad hacia atrás

- El campo `questions` del `intake_plan` sigue siendo una lista de dicts con la misma estructura que antes, pero sin elementos `question_type="I"`.
- El campo `inventory_summary` es nuevo y opcional para el frontend: si no existe (sesiones antiguas), el panel de estado simplemente no lo renderiza.
- El campo `inventory_pending_count` en `summary` es nuevo y aditivo: no rompe código que ya lee `blocking_count`, `critical_count`, etc.

---

## Propiedades de Corrección

*Una propiedad es una característica o comportamiento que debe ser verdadero en todas las ejecuciones válidas del sistema — esencialmente, una declaración formal sobre lo que el sistema debe hacer. Las propiedades sirven como puente entre las especificaciones legibles por humanos y las garantías de corrección verificables por máquina.*

### Propiedad 1: El campo `questions` nunca contiene pendientes de inventario

*Para cualquier* `session_state` con un `document_inventory` válido (con cero o más ítems pendientes), el `intake_plan` generado por `IntakePlannerAgent` SHALL tener un campo `questions` que no contenga ningún elemento con `question_type="I"` ni con `field_target` que comience con `"inventory."`.

**Valida: Requisitos 1.1, 4.1**

### Propiedad 2: `inventory_summary` contiene todos los grupos de inventario con estructura completa

*Para cualquier* `session_state` con un `document_inventory` que tenga ítems pendientes agrupados en N categorías, el `intake_plan` generado SHALL tener un campo `inventory_summary` con exactamente N elementos, cada uno conteniendo los campos `category`, `count`, `priority`, `field_target` y `table_data`.

**Valida: Requisitos 1.2, 1.3, 3.1**

### Propiedad 3: El sanitize elimina todos los pendientes de inventario

*Para cualquier* lista `pending_questions` que contenga una mezcla arbitraria de pendientes con `question_type="I"`, `field_target` con prefijo `"inventory."`, y pendientes de otros tipos, el resultado de `_sanitize_economic_pending_questions` SHALL no contener ningún elemento con `question_type="I"` ni con `field_target` que comience con `"inventory."`.

**Valida: Requisitos 2.1, 2.2, 2.5**

### Propiedad 4: El sanitize preserva los pendientes no-inventario

*Para cualquier* lista `pending_questions` que contenga pendientes de tipos `"B"`, `"Q"`, `"A"`, `"economic_price"`, `"profile_field"` u otros tipos no-inventario, el resultado de `_sanitize_economic_pending_questions` SHALL contener exactamente los mismos elementos no-inventario (sin modificación de ningún campo).

**Valida: Requisitos 2.4, 4.1, 4.2**

### Propiedad 5: `summary.inventory_pending_count` es la suma de los `count` de `inventory_summary`

*Para cualquier* `session_state` con un `document_inventory` válido, el campo `summary.inventory_pending_count` del `intake_plan` generado SHALL ser igual a la suma de los campos `count` de todos los elementos en `inventory_summary`.

**Valida: Requisitos 5.1, 5.2**

### Propiedad 6: Los conteos del `summary` excluyen los pendientes de inventario

*Para cualquier* `session_state`, la suma `blocking_count + critical_count + important_count + complementary_count` del `summary` SHALL ser igual a `len(questions)`, sin incluir ningún pendiente de inventario.

**Valida: Requisito 5.1**

---

## Manejo de Errores

### `IntakePlannerAgent._inventory_summary_from_inventory`

- Si `session_state.get("document_inventory")` no es un dict → retornar `[]` (mismo comportamiento que antes).
- Si `items` está vacío o no hay ítems con `status` que termine en `"pending"` → retornar `[]`.
- Si un ítem del inventario no tiene `category` → usar `"legal_administrative"` como fallback.
- Si la tabla Markdown no puede construirse (lista vacía) → incluir `table_data` como cadena vacía `""`.

### `ChatbotRAGAgent._sanitize_economic_pending_questions`

- El filtro de inventario es silencioso: nunca lanza excepciones.
- Si `question_type` o `field_target` no están presentes en un pendiente → el pendiente se preserva (fail-open para no-inventario).
- El log de descarte incluye `question_id` y `reason="inventory_silent_processing"` para auditoría.

---

## Estrategia de Testing

### Tests unitarios

- `test_intake_planner_inventory_not_in_questions`: verificar que `questions` no contiene `question_type="I"` con un inventario de ejemplo.
- `test_intake_planner_inventory_summary_empty_when_no_pending`: verificar que `inventory_summary=[]` cuando no hay ítems pendientes.
- `test_chatbot_sanitize_preserves_b_and_q_questions`: verificar que los pendientes B y Q no se tocan.
- `test_chatbot_sanitize_logs_discarded_inventory`: verificar que se emite el log INFO al descartar.

### Tests de propiedades (Hypothesis)

El proyecto ya usa Hypothesis (ver `.hypothesis/` en la raíz). Se usará Hypothesis para los tests de propiedades.

Cada test de propiedad debe ejecutarse con mínimo 100 iteraciones (`@settings(max_examples=100)`).

- **Propiedad 1**: Generar `session_state` con `document_inventory` aleatorio → verificar que `questions` no contiene `question_type="I"`.
- **Propiedad 2**: Generar inventarios con N categorías aleatorias → verificar estructura de `inventory_summary`.
- **Propiedad 3**: Generar listas `pending_questions` mixtas → verificar que el sanitize elimina todos los de inventario.
- **Propiedad 4**: Generar listas `pending_questions` con tipos no-inventario → verificar que se preservan intactos.
- **Propiedad 5**: Generar inventarios aleatorios → verificar que `inventory_pending_count == sum(item["count"])`.
- **Propiedad 6**: Generar `session_state` completo → verificar que `sum(counts) == len(questions)`.

### Cobertura de edge cases

- Inventario con 0 ítems pendientes → `inventory_summary=[]`, `inventory_pending_count=0`.
- Inventario con ítems en una sola categoría → `inventory_summary` con 1 elemento.
- `pending_questions` vacío → sanitize retorna `[]` sin errores.
- Pendiente con `question_type` ausente y `field_target="inventory.technical.completion"` → debe ser descartado por el prefijo.
- Sesión antigua con `INTAKE-INV-LEGAL_ADMINISTRATIVE` en `pending_questions` → descartado en el primer sanitize.
