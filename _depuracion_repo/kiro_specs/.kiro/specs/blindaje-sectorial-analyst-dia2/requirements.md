# Requisitos: Día 2 — Clasificación Sectorial en Analyst

## Contexto

El roadmap de blindaje multisectorial requiere que `AnalystAgent` deje de operar con un único perfil implícito y explicite el **sector dominante de la licitación** con evidencia verificable.

Objetivo de negocio: reducir sesgo por vertical (servicios) y mejorar la precisión de checklist, intake y recomendaciones para sectores como:
- obra pública,
- salud,
- adquisiciones/suministro,
- servicios generales,
- TIC.

## Objetivo

Incorporar en la salida canónica del analista un bloque de clasificación sectorial con:
1. etiqueta de sector,
2. confianza,
3. evidencia textual trazable,
4. ruta de fallback segura cuando la señal sea ambigua.

## Requisitos funcionales

### R1 — Clasificación sectorial canónica
- `AnalystAgent` debe producir `sector_classification` en `extracted_data`.
- Estructura mínima:
  - `sector_id` (`obra_publica`, `salud`, `adquisiciones`, `servicios`, `tic`, `mixto`, `indeterminado`)
  - `confidence` (`0.0` a `1.0`)
  - `method` (`rule_based`, `llm_assisted`, `hybrid`)
  - `evidence` (lista de hallazgos literales)

### R2 — Evidencia textual obligatoria
- Cada evidencia debe incluir:
  - `snippet` literal,
  - `signal_code` estable (ej. `OP_MAQUINARIA`, `SALUD_REG_SANITARIO`),
  - `source_hint` (sección o aproximación de origen),
  - `weight`.
- Si no hay evidencia suficiente, no se debe “forzar” sector: usar `indeterminado`.

### R3 — Política de decisión conservadora
- Cuando existan señales fuertes de más de un sector:
  - si la diferencia de puntaje es menor al umbral definido, clasificar como `mixto`.
- Cuando la confianza global sea menor al umbral mínimo:
  - clasificar como `indeterminado`.

### R4 — Ajuste de prompts iniciales del Analyst
- El prompt de extracción debe incorporar instrucción explícita para:
  - identificar señales sectoriales,
  - devolver evidencia literal,
  - evitar inferencias sin ancla textual.
- Se debe mantener compatibilidad con extracción actual (cronograma, solvencias, alcance, etc.).

### R5 — Propagación para capas siguientes
- `sector_classification` debe quedar disponible para:
  - `IntakePlannerAgent`,
  - flujos de `DataGap`,
  - diagnóstico/telemetría del orquestador (sin bloqueo en Día 2).

## Requisitos no funcionales

### N1 — Determinismo operativo
- Debe existir núcleo rule-based replicable para señales críticas, aun si falla LLM.

### N2 — Auditabilidad
- Toda clasificación debe ser explicable por evidencia literal y pesos.

### N3 — Backward compatibility
- No romper consumidores existentes de `extracted_data`.
- Campos nuevos deben ser aditivos.

### N4 — Preparación para vertical México
- Diseño listo para ampliar catálogo de señales por sector sin refactor mayor.

## Criterios de aceptación

- El analista devuelve `sector_classification` en sesiones nuevas.
- Para casos con señales claras de obra pública, `sector_id` no queda en `servicios` por default.
- Si no hay señales claras, la salida es `indeterminado` con confianza baja (no inventada).
- El bloque contiene evidencia literal útil para revisión humana.
- No se degradan los campos previos del analista.
