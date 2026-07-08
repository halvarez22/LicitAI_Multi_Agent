# Requisitos: Document Field Policy Registry (Day 2)

## Contexto

El `DocumentFillQualityGateService` actual valida con reglas genéricas (placeholders, campos faltantes globales, anclas económicas).

Para cerrar robustez enterprise, se requiere una matriz explícita de políticas por tipo documental/campo crítico y activar validación por confianza de procedencia.

## Objetivo

Evolucionar el gate de llenado para que valide con reglas **específicas por documento** y con soporte a `source_confidence_insufficient` en campos críticos.

## Requisitos funcionales

### R1 — Registro versionado de políticas por documento
- Debe existir un registro canónico versionado (`policy_version`) que describa políticas por:
  - familia (`technical`, `formats`, `economic`),
  - tipo documental,
  - campo crítico.
- Cada política debe definir:
  - `field_key`,
  - `required` (bool),
  - `allow_placeholder` (bool),
  - `expected_type` (`text|numeric|date|identifier`),
  - `consistency_group` (opcional),
  - `min_confidence` (opcional para campos críticos).

### R2 — Selección de política por documento generado
- El gate debe resolver qué política aplicar por documento usando:
  1) `tipo` del writer, si existe,
  2) `template_id`, si existe,
  3) nombre/canonical-id del archivo (fallback determinista).

### R3 — Reglas de validación por campo
- Para cada campo marcado `required=true`:
  - bloquear si está vacío o inválido según tipo.
- Para `allow_placeholder=false`:
  - bloquear si el valor cae en patrones de placeholder.
- Para `expected_type=numeric`:
  - validar coerción segura (sin silencios).

### R4 — Regla de confianza de procedencia
- Si un campo crítico define `min_confidence`, el gate debe emitir:
  - `source_confidence_insufficient` cuando `confidence < min_confidence`.
- Debe incluirse evidencia de procedencia por campo:
  - `source`,
  - `confidence`,
  - `anchor` (si aplica).

### R5 — Consistencia cruzada por grupos
- Para campos en mismo `consistency_group`, validar consistencia mínima.
- En económico:
  - subtotal/IVA/total numéricos y coherentes.

### R6 — Contrato de salida extendido
- `document_fill_quality_gate` debe incluir:
  - `policy_version`,
  - `documents_with_policy`,
  - `issues` enriquecidos con política aplicada.

### R7 — Compatibilidad con modo `audit`
- En `audit`, las violaciones se reportan como warning sin detener flujo.
- Debe existir telemetría de potenciales falsos positivos para calibración.

## Requisitos no funcionales

### N1 — Determinismo
- A igualdad de archivo + política + contexto de procedencia, el resultado debe ser estable.

### N2 — Extensibilidad
- Añadir nuevos documentos/políticas no debe requerir cambios intrusivos en writers.

### N3 — Rendimiento
- La resolución de políticas no debe aumentar latencia del gate de forma significativa.

## Criterios de aceptación (de especificación)

- Existe catálogo de políticas para las 3 familias documentales.
- Existe mapeo explícito de al menos:
  - anexo económico,
  - carta compromiso económica,
  - carta técnica presentación,
  - anexo legal templated.
- Existe contrato de procedencia para activar `source_confidence_insufficient`.
