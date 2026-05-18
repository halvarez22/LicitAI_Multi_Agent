# Diagnóstico — P0 Cuadratura Determinista

## Síntoma observado en prueba
- `line_items_count = 14`
- `excel_total = 26931.25`
- `engine_total = 0.0`
- `delta_total = -26931.25`
- `stop_reason = ECONOMIC_GAP`

## Evidencia operacional
- La ingesta del Excel sí persistió filas en `session_line_items`.
- El cálculo de propuesta en ciertos escenarios no derivó ítems económicos efectivos desde esas filas.
- El validador de cuadratura funcionó correctamente al bloquear inconsistencia.

## Causa raíz probable
1. Dependencia del flujo LLM para construir `proposal_draft` cotizable.
2. Ausencia de ruta determinista completa en todos los caminos de generación.
3. Desacople entre normalización tabular y armado final de ítems para cálculo.

## Riesgo
- Alto (P0): posible descalificación por discrepancia económica.
- Reputacional: pérdida de confianza en salida económica automática.

## Estado actual tras mitigación
- Se aplicó fallback determinista en `EconomicAgent`.
- Se alcanzó `delta_total = 0.0` en corrida de validación.
- Pendiente: hardening estructural y regresión E2E obligatoria.

## Hipótesis a validar en sprint
1. El fallback cubre todos los perfiles económicos frecuentes.
2. No introduce duplicidad de líneas al coexistir propuesta LLM + tabular.
3. El reporte de cuadratura mantiene coherencia por línea y total.
