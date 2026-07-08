# Requisitos: Fast Track Document Candidate List (Human-Confirm)

## Contexto

El flujo actual prioriza validación automática estricta antes de entregar una lista accionable de documentos, lo que en hardware local limitado (8GB VRAM) aumenta latencia, ruido y bloqueos por incertidumbre.

Se requiere un carril de alta velocidad que entregue una propuesta documental útil en segundos, con validación humana mínima y trazable.

## Objetivo

Implementar un modo Fast Track donde el sistema:
1. proponga una lista candidata de documentos (generar/presentar_fisico/informativo),
2. permita confirmación/ajuste humano rápido,
3. revalide y continúe generación con seguridad preservada.

## Requisitos funcionales

### R1 — Lista candidata rápida
- El sistema debe emitir una `candidate_document_list` temprana por sesión.
- La lista debe incluir al menos:
  - `document_id`
  - `nombre`
  - `categoria` (administrativo/tecnico/economico)
  - `tipo_accion_propuesto` (`generar|presentar_fisico|informativo`)
  - `confidence`
  - `evidence_snippet`

### R2 — Confirmación humana de baja fricción
- El usuario debe poder confirmar o ajustar `tipo_accion` por documento.
- UX objetivo: resolver en pocos pasos (no cientos de preguntas).
- Cambios deben persistirse como override auditable.

### R3 — Precedencia explícita HITL
- La decisión final de acción por documento debe respetar:
  `usuario_confirmado > clasificación automática`.
- Debe existir rastro de quién/qué cambió (`source=user_override`).

### R4 — Seguridad no relajable
- El Fast Track no elimina gates críticos.
- Tras confirmación humana, el sistema debe ejecutar validaciones finales antes de generar.
- Placeholders y faltantes críticos siguen bloqueando.

### R5 — Integración con generación
- Writers deben consumir lista final reconciliada.
- No deben generar documentos marcados como `informativo` o `presentar_fisico`.

### R6 — Manejo de no-aplica explícito
- Debe existir estado documentado de “no aplica” para anexos detectados pero excluidos por bases.
- Ejemplo esperado: excluir anexos marcados explícitamente como “NO APLICA”.

### R7 — Contrato de salida para UI/Chat
- Debe exponerse:
  - `candidate_document_list`
  - `candidate_summary` (totales por tipo)
  - `needs_human_confirmation` (bool)
  - `unresolved_count`

## Requisitos no funcionales

### N1 — Optimización para 8GB VRAM
- Reducir llamadas LLM encadenadas para clasificación documental.
- Evitar ciclos de reintento costosos previos a propuesta inicial.

### N2 — Trazabilidad
- Guardar versión de lista candidata y versión confirmada.
- Guardar deltas por documento.

### N3 — Compatibilidad progresiva
- Feature flag para activar/desactivar Fast Track sin romper flujo legacy.

## Criterios de aceptación

- Se obtiene lista candidata utilizable en tiempo significativamente menor al flujo actual.
- Usuario puede confirmar/ajustar clasificación documental con mínimo esfuerzo.
- Después de confirmación, el sistema genera solo documentos correctos.
- Gates críticos permanecen activos y auditables.
