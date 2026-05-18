# Requisitos: Contrato canónico documental y filtro por acción

## Problema

La extracción del `ComplianceAgent` solicita al LLM `tipo_accion` (`generar`, `presentar_fisico`, `informativo`), pero en la normalización se pierde ese campo. Los redactores (`technical_writer`, `formats`) quedan forzados a heurísticas por texto y sobre-generan documentos.

## Objetivo

Alinear todo el pipeline para que:

1. La semántica de acción sobreviva del `map` al resultado final.
2. Los redactores prioricen el contrato canónico (`tipo_accion`) y solo usen heurísticas como fallback.
3. Se registre trazabilidad del nivel de tipado para auditar calidad.

## Requisitos funcionales

### R1 — Preservación de contrato en Compliance
- `ComplianceAgent._normalize_item` debe preservar:
  - `tipo_accion`
  - `categoria_sugerida`
  - `action_confidence`
- Si `tipo_accion` viene vacío o inválido, normalizar a `unknown`.

### R2 — Writers orientados a acción
- `TechnicalWriter` y `Formats` deben:
  - procesar `tipo_accion=="generar"` como ruta principal;
  - excluir `informativo` y `presentar_fisico`;
  - usar heurísticas solo cuando `tipo_accion=="unknown"` (compatibilidad retro).

### R3 — Trazabilidad en salidas
- `Compliance` debe exponer métricas agregadas de `tipo_accion`.
- `TechnicalWriter` y `Formats` deben reportar conteo de candidatos por acción en sus `result_data`.

## No funcionales

- Mantener compatibilidad con sesiones históricas sin `tipo_accion`.
- No romper formato existente de `compliance_master_list`.
