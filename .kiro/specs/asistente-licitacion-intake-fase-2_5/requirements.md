# Requisitos: Asistente de Intake Fase 2.5 (Cierre UX)

## Contexto

Fase 2 dejó operativo el intake proactivo con opt-in y promoción a `pending_questions`.
La Fase 2.5 cierra la experiencia de usuario para operación diaria con tres objetivos:

1. tono ejecutivo (consultor senior),
2. progreso explícito (`Pregunta X de N`),
3. reanudación exacta tras refresh/reingreso.

## Objetivo

Mejorar claridad, confianza y continuidad del flujo de intake sin cambiar la lógica de negocio ni romper compatibilidad legacy.

## Requisitos funcionales

### R1 — Copy ejecutivo estandarizado
- Los mensajes de oferta y seguimiento de intake deben usar tono:
  - claro,
  - accionable,
  - profesional (sin tecnicismos innecesarios).
- Debe existir un set de plantillas de copy por estado:
  - `offer`,
  - `accepted_start`,
  - `question_prompt`,
  - `resume_prompt`,
  - `completed`.

### R2 — Indicador de progreso en cada turno de captura
- Cuando exista flujo intake activo, cada pregunta debe incluir:
  - `progress_current`
  - `progress_total`
  - `progress_label` (ej. `Pregunta 2 de 5`)
- Debe contemplar cola dinámica (si se elimina/añade pendiente).

### R3 — Reanudación exacta de sesión
- Si el usuario refresca o regresa luego, el chatbot debe continuar en:
  - mismo `current_question_index`,
  - misma cola efectiva,
  - mismo `question_id` (si aplica).
- Debe preferir `intake_progress.current_question_id` cuando exista, con fallback a índice.

### R4 — Estado de intake explícito en sesión
- Persistir estructura mínima:
  - `intake_progress.started`
  - `intake_progress.accepted`
  - `intake_progress.current_question_id`
  - `intake_progress.remaining`
  - `intake_progress.total`
  - `intake_progress.last_prompt_at`

### R5 — Mensaje de resumen al retomar
- En reingreso con flujo activo, el primer mensaje debe indicar:
  - cuántas faltan,
  - cuál es la siguiente,
  - por qué importa (si es bloqueante/crítico).

### R6 — Compatibilidad con pending legacy
- El progreso visual debe funcionar tanto para:
  - cola proveniente de `intake_plan`,
  - cola legacy (`DataGap`, económico, etc.).

## Requisitos no funcionales

### N1 — No intrusivo
- No repetir saludo proactivo en bucle durante una misma sesión activa.

### N2 — Observabilidad
- Log de eventos clave:
  - `intake_offer_shown`,
  - `intake_resumed`,
  - `intake_progress_prompted`.

### N3 — Robustez
- Si `question_id` no existe, fallback seguro a índice sin romper conversación.

## Criterios de aceptación

- El usuario ve progreso explícito en cada pregunta.
- Tras refresh, el bot retoma exactamente donde quedó.
- El copy mantiene tono ejecutivo consistente.
- No se rompen flujos existentes de captura/rescate/RAG.
