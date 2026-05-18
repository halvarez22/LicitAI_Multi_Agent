# Requisitos: Calidad de llenado documental (Punto 2)

## Contexto

El problema de sobre-generación documental (Punto 1) ya fue mitigado con preservación de `tipo_accion` y gate de calidad de clasificación.

Permanece abierto el Punto 2: hoy el sistema puede generar documentos con estructura válida pero con llenado incompleto, datos débiles (`N/A`, `...`, textos genéricos), o inconsistencias entre campos críticos.

## Objetivo

Asegurar que **ningún documento final** (técnico, administrativo, económico) se marque como `success` si no cumple un estándar mínimo verificable de llenado correcto y consistencia de datos.

## Requisitos funcionales

### R1 — Validación post-generación obligatoria
- Debe existir una validación **después** de generar archivos (DOCX/XLSX) y **antes** de confirmar éxito de etapa.
- La validación debe inspeccionar contenido materializado y no solo payloads intermedios.

### R2 — Reglas canónicas de bloqueo por llenado
- El sistema debe bloquear (`WAITING_FOR_DATA`) cuando detecte cualquiera de las siguientes clases:
  1. `placeholder_detected` (tokens de relleno o textos de “dato pendiente” en campos críticos).
  2. `required_field_missing` (campo obligatorio de documento sin valor útil).
  3. `cross_field_inconsistency` (inconsistencia entre campos relacionados, p. ej. razón social/RFC/representante).
  4. `source_confidence_insufficient` (dato derivado de fuente con confianza menor al umbral para campos críticos).

### R3 — Matriz mínima de campos críticos por familia documental
- Debe existir una matriz versionada de “campos críticos por tipo de documento” para:
  - `technical_writer` (carta técnica + documentos técnicos generados).
  - `formats` (administrativos/legales).
  - `economic_writer` (anexo económico, carta de precios, tabla de precios).
- La ausencia de campos críticos en esa matriz impide certificar calidad de llenado.

### R4 — Cascada de precedencia explícita en el llenado
- Para cada campo crítico, el llenado debe respetar la precedencia:
  `usuario directo (HITL) > documento normalizado > catálogo maestro > inferencia LLM/RAG`.
- Debe poder evidenciarse la fuente ganadora por campo.

### R5 — Evidencia y procedencia por hallazgo
- Cada hallazgo de calidad debe incluir:
  - `error_type` estable.
  - `document_id` / `filename`.
  - `field_key` (si aplica).
  - `detected_value`.
  - `expected_rule`.
  - `provenance` (source + confidence + anchor si existe).

### R6 — Integración con UX de validaciones
- Los bloqueos de llenado deben publicarse como `validation_events` para UI.
- Debe existir mapeo UX en `validation_mapping.json` para cada `error_type` de R2.

### R7 — Contrato de salida del gate
- El resultado del gate de llenado debe incluir:
  - `validation_passed` (bool),
  - `blocking_count`,
  - `warning_count`,
  - `issues[]` estructurados,
  - `documents_scanned`.
- Si `validation_passed=false` con bloqueantes, la etapa responde `WAITING_FOR_DATA`.

### R8 — No degradar determinismo económico
- El validador de llenado no debe alterar cálculos económicos.
- Solo valida consistencia/llenado en salida; no cambia reglas fiscales.

## Requisitos no funcionales

### N1 — Trazabilidad y auditoría
- Cada corrida debe persistir resumen del gate en sesión para rehidratación UI.
- Debe poder reconstruirse por qué un documento se bloqueó.

### N2 — Determinismo reproducible
- El resultado del gate para un mismo conjunto de archivos y estado de sesión debe ser estable.

### N3 — Performance operativa
- La validación post-generación no debe incrementar tiempo total de generación por encima de un umbral configurable (objetivo inicial: +10% máximo por corrida típica).

### N4 — Compatibilidad progresiva
- Se permite rollout por flags:
  - modo auditoría (solo reporta),
  - modo bloqueo (enforce).

## Fuera de alcance (esta fase de diseño)

- Corrección automática del contenido por IA dentro del gate.
- Reescritura masiva de prompts.
- Validación jurídica semántica completa “nivel abogado” de cada cláusula.
