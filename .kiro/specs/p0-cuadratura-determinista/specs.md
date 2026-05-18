# SPEC — P0 Cuadratura Determinista Excel ↔ Motor Económico

## Objetivo
Eliminar divergencias entre el total económico del motor y el total del Excel de cotización, garantizando `|delta_total| <= 0.01` en corridas productivas.

## Contexto de negocio
- El riesgo económico es causal directa de descalificación.
- Se logró cierre de prueba con fallback, pero se requiere una ruta determinista sin depender de comportamiento LLM.

## Problema actual
- Existen escenarios donde `session_line_items` contiene filas válidas, pero la propuesta económica queda vacía o en cero.
- Resultado: `engine_total = 0` con `excel_total > 0`.

## Alcance
1. Mapeo canónico de filas tabulares a partidas económicas.
2. Cálculo de propuesta desde fuente determinista cuando no haya propuesta LLM válida.
3. Validación de cuadratura obligatoria.
4. Trazabilidad y diagnóstico en API/UI.

## Fuera de alcance
- Cambios de UX amplios en paneles.
- Reingeniería completa del módulo económico.

## Requisitos funcionales
1. El sistema debe construir `proposal_items` deterministas desde `session_line_items` cuando falte propuesta cotizable.
2. La cuadratura debe bloquear sólo si `abs(delta_total) > 0.01`.
3. Debe persistirse evidencia de fuente por línea (`session_line_items`, `fallback`, `manual override`).
4. Debe exponer reporte de cuadratura consumible por API para inspección operativa.

## Requisitos no funcionales
- Determinismo: misma entrada tabular => mismo total.
- Auditabilidad: cada subtotal debe ser trazable a fila origen.
- Performance: sin degradar tiempos de generación de forma perceptible.

## Criterios de aceptación
1. Con fixture ISSSTE vigilancia:
   - `line_items_count > 0`
   - `engine_total == excel_total` (tolerancia 0.01)
   - `blocking == false`
2. Sin filas tabulares:
   - comportamiento previo conservado.
3. Tests de regresión pasan en económico/compliance relacionados.

## Métricas de éxito
- `economic_gap_rate` por cuadratura < 5% en sesiones con Excel válido.
- `delta_total` mediano = 0.
- tiempo de resolución manual de gaps económicos disminuye >= 50%.
