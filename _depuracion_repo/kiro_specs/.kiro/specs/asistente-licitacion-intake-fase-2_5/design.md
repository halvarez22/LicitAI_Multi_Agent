# Diseño: Asistente de Intake Fase 2.5

## Alcance del diseño

Se limita a UX conversacional y estado de reanudación. No cambia reglas de priorización del planner ni motor RAG.

## Componentes a ajustar

### 1) `ChatbotRAGAgent` (principal)
- Incorporar helper de progreso:
  - `_compute_pending_progress(pending, current_idx)`
- Incorporar helper de copy ejecutivo:
  - `_render_intake_message(template_key, context)`
- Incorporar helper de resume:
  - `_resolve_resume_pointer(session_state, pending_questions)`

### 2) Estado de sesión
- Estructura `intake_progress` unificada:
  - `started: bool`
  - `accepted: bool`
  - `total: int`
  - `remaining: int`
  - `current_question_id: str | null`
  - `last_prompt_at: iso`

### 3) Plantillas de copy
- Diccionario interno (sin i18n por ahora) con placeholders:
  - `offer`: resumen con bloqueantes/pendientes
  - `question_prompt`: incluye `Pregunta X de N`
  - `resume_prompt`: “Retomamos donde quedamos...”
  - `completed`: cierre ejecutivo

## Flujo conversacional objetivo

1. Usuario saluda / pide avance.
2. Si hay intake activo:
   - resolver puntero exacto (`question_id` preferente),
   - mostrar `resume_prompt` + `Pregunta X de N`.
3. Si no hay intake activo y hay plan:
   - mostrar `offer`.
4. Si usuario acepta:
   - iniciar cola y guardar `intake_progress`.

## Resolución de puntero (exact resume)

Orden:
1. Buscar `intake_progress.current_question_id` en cola actual.
2. Si no existe, usar `current_question_index`.
3. Si índice fuera de rango, clamp seguro `[0, len-1]`.

## Compatibilidad legacy

- Para preguntas sin `question_id`:
  - generar id derivado estable (`field + hash breve de question`) solo en memoria.
- No mutar schema legacy salvo `intake_progress`.

## Contrato de respuesta (data)

Cuando tipo sea pendiente/intake:

```json
{
  "tipo": "pending_question|intake_resume|intake_offer",
  "respuesta": "texto ejecutivo ...",
  "progress_current": 2,
  "progress_total": 5,
  "progress_label": "Pregunta 2 de 5"
}
```

## Telemetría propuesta

- `intake_offer_shown` (session_id, blocking_count, total)
- `intake_resumed` (session_id, current_question_id, remaining)
- `intake_progress_prompted` (session_id, idx, total)

## Riesgos y mitigaciones

- Riesgo: progreso desfasado por cambios en cola.
  - Mitigación: recalcular `total/remaining` en cada turno.
- Riesgo: reanudación ambigua en legacy.
  - Mitigación: fallback por índice + clamp.
- Riesgo: exceso de texto.
  - Mitigación: plantillas cortas con contexto mínimo accionable.
