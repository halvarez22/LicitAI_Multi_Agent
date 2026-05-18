# Plan de Implementación — P0 Cuadratura Determinista

## Fase 1 — Hardening del flujo económico
1. [ ] Consolidar ruta determinista `session_line_items -> proposal_items`.
2. [ ] Asegurar cálculo de `subtotal` robusto con `cantidad`, `precio_unitario`, `importe/subtotal` fuente.
3. [ ] Evitar doble conteo cuando coexistan ítems LLM y tabulares.

## Fase 2 — Validación y trazabilidad
4. [ ] Estandarizar `price_source` y `provenance_ui` para líneas económicas.
5. [ ] Asegurar persistencia de `quadrature_report` en salida de economic.
6. [ ] Exponer resumen de cuadratura para monitoreo/API.

## Fase 3 — Pruebas
7. [ ] Unit tests:
   - bootstrap desde tabular,
   - no sobrescribir propuesta válida,
   - tolerancia de redondeo.
8. [ ] E2E de sesión ISSSTE con Excel real:
   - `line_items_count > 0`
   - `blocking=false`
   - `delta_total <= 0.01`
9. [ ] Regresión sobre casos previos sin Excel.

## Fase 4 — Operación
10. [ ] Agregar tablero de verificación rápida (engine_total, excel_total, delta_total).
11. [ ] Definir playbook de rollback (feature flag fallback determinista).

## Entregables
- Código hardenizado en `EconomicAgent`/motor.
- Suite de pruebas unitarias + E2E.
- Evidencia de corrida ISSSTE con `delta_total=0.0`.
- Nota de operación para soporte técnico.
