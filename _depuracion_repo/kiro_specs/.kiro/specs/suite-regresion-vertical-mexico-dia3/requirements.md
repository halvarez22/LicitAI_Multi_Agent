# Requisitos: Día 3 — Suite de Regresión Vertical México

## Contexto

Con la clasificación sectorial ya implementada en `AnalystAgent`, el siguiente paso es validar robustez con casos representativos de México para evitar sesgo por vertical y medir calidad real del diagnóstico.

Esta suite no busca solo “pasar tests”, sino certificar:
- exactitud sectorial,
- trazabilidad de evidencia,
- estabilidad de extracción base (sin regresiones en cronograma/participación/económico).

## Objetivo

Definir y ejecutar una suite de regresión por vertical con 4 casos:
1. Obra pública
2. Salud
3. Adquisiciones
4. Servicios

## Requisitos funcionales

### R1 — Cobertura mínima por vertical
- Debe existir al menos 1 fixture por vertical:
  - `obra_publica`
  - `salud`
  - `adquisiciones`
  - `servicios`
- Cada fixture debe incluir texto suficiente para:
  - clasificación sectorial,
  - evidencia literal (`snippet`),
  - extracción base mínima del analista.

### R2 — Asserts de clasificación sectorial
- Cada caso debe validar:
  - `sector_classification.sector_id` esperado (o permitido en casos ambiguos),
  - `confidence` no nulo,
  - `evidence` no vacía cuando hay señales fuertes.

### R3 — Trazabilidad obligatoria
- En todos los casos con señal fuerte, al menos una evidencia debe contener:
  - `signal_code` del sector esperado,
  - `snippet` literal legible.

### R4 — No regresión del núcleo del Analyst
- La suite debe confirmar que siguen presentes campos base:
  - `cronograma`
  - `requisitos_participacion`
  - `reglas_economicas`
  - `alcance_operativo`

### R5 — Política de ambigüedad
- Debe existir al menos 1 caso (o subcaso) que valide resolución conservadora:
  - `mixto` o `indeterminado` según umbrales.

## Requisitos no funcionales

### N1 — Reproducibilidad
- Fixtures deterministas (texto estático en repo).
- Sin dependencia de servicios externos para la evaluación principal.

### N2 — Privacidad y cumplimiento
- Datos anonimizados (sin PII sensible no necesaria).
- Uso de extractos representativos, no documentos productivos crudos.

### N3 — Mantenibilidad
- Estructura de fixtures versionable y fácil de ampliar por vertical.

## Criterios de aceptación

- Suite corre en CI/local y produce resultado estable.
- Cada vertical queda cubierta con asserts explícitos de clasificación y evidencia.
- No se reportan regresiones del contrato base del analista en los 4 casos.
- Existe reporte resumido por vertical (pass/fail + hallazgos clave).
