# Requisitos: Integración Quality Hints -> Intake Planner/Chat

## Contexto

El sistema bloquea correctamente cuando la calidad documental no es suficiente (`document_quality_gate` y/o `document_fill_quality_gate`), pero la UX actual no siempre convierte ese bloqueo en una conversación accionable para el usuario.

Resultado actual:
- el muro de seguridad funciona,
- pero la ruta de desbloqueo por chat/intake es incompleta.

## Objetivo

Conectar los hints de calidad persistidos en sesión con el flujo de intake/chat para que, ante bloqueo, el sistema formule preguntas claras y orientadas a resolución.

## Requisitos funcionales

### R1 — IntakePlanner debe consumir hints de calidad
- `IntakePlannerAgent` debe leer:
  - `last_document_quality_waiting_hints`
  - `last_document_fill_quality_waiting_hints`
- Debe transformarlos a preguntas priorizadas de intake.

### R2 — Nueva fuente de preguntas en planner
- Crear método dedicado (ej. `_questions_from_quality_hints`).
- Debe mapear errores/hints a preguntas de negocio (no técnicas).

### R3 — Tipología de pregunta para bloqueos de calidad
- Introducir tipo explícito de pendiente para calidad:
  - `quality_validation_blocking`
- Debe incluir metadatos de trazabilidad:
  - `error_type`
  - `document_id`/`field_key` (si aplica)
  - `hint_source` (`document_quality_gate` o `document_fill_quality_gate`)

### R4 — Copy ejecutivo y accionable
- Las preguntas no deben exponer jerga técnica cruda.
- Deben pedirse decisiones concretas de usuario, por ejemplo:
  - confirmar si un documento es generable/presentable/informativo,
  - confirmar obligatoriedad de anexo ambiguo,
  - corregir dato faltante crítico.

### R5 — Priorización y deduplicación
- Preguntas de calidad deben entrar con prioridad alta:
  - `BLOQUEANTE` o `CRITICO` según severidad.
- Debe evitarse duplicar preguntas equivalentes (dedupe semántico por `field_target`/`question`).

### R6 — Integración con ChatbotRAG
- Si existen `quality_validation_blocking`, el chatbot debe:
  - mostrarlas como paso siguiente recomendado,
  - preservar progresión (`progress_current/total/label`),
  - permitir retomar exactamente el punto bloqueado.

### R7 — Revalidación tras respuesta de usuario
- Al resolver pregunta de calidad, el sistema debe permitir revalidar y continuar flujo de generación.
- Si persiste bloqueo, debe devolver nueva pregunta concreta (no mensaje genérico repetido).

## Requisitos no funcionales

### N1 — Seguridad no relajable
- Esta integración **no** debe desactivar gates ni permitir bypass automático.
- Solo agrega canal de resolución asistida.

### N2 — Trazabilidad forense
- Toda pregunta generada desde hints debe conservar referencia a causa raíz.

### N3 — Compatibilidad retro
- No romper intake legacy (`pending_questions` existentes).
- Comportamiento aditivo.

## Criterios de aceptación

- Ante bloqueo de calidad en generación, el usuario recibe al menos una pregunta accionable de desbloqueo.
- La pregunta es comprensible para negocio y enlaza con la causa raíz.
- Al responder, se observa intento de revalidación y avance o nueva acción concreta.
- No se generan documentos mientras el bloqueo crítico siga activo.
