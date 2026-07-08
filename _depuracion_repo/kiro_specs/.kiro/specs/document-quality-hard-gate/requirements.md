# Requisitos: Gate duro de calidad documental

## Contexto

Aun preservando `tipo_accion`, pueden llegar listas degradadas (alto `unknown`, baja evidencia, cero `generar`) que disparan generación masiva de bajo valor legal.

## Requisitos funcionales

### R1 — Gate en writers
- `TechnicalWriter` y `Formats` deben bloquear (`WAITING_FOR_DATA`) cuando la calidad de clasificación documental no cumple umbrales.

### R2 — Reglas de bloqueo
- Si `total_items >= min_items` y:
  1) `generar_count == 0`, o
  2) `unknown_ratio > max_unknown_ratio`, o
  3) `evidence_match_ratio < min_evidence_match_ratio`,
  entonces se bloquea la generación.

### R3 — Trazabilidad
- El bloqueo debe registrar:
  - `reason` (`no_actionable_generate_items`, `unknown_ratio_above_threshold`, `evidence_match_ratio_below_threshold`);
  - `metrics` completas en payload.
- Debe crear `pending_questions` tipo `document_quality_gate_blocking`.

## Requisitos no funcionales

- Umbrales configurables por settings/env.
- Compatibilidad: si la lista es pequeña (`< min_items`), no bloquear automáticamente.
