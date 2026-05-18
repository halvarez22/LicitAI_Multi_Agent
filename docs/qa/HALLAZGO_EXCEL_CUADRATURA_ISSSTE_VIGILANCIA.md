# Hallazgo: cuadratura economica Excel vs motor (ISSSTE Vigilancia)

## Contexto

- Sesion: `unaq_final_d41d7dea`
- Job generacion: `f3d88d62-2d9b-4155-8407-3fd1332e3aa9`
- Estado: `waiting_for_data`
- Stop reason: `ECONOMIC_GAP`

## Sintoma observado

- El motor economico reporta:
  - `engine_total = 0.0`
  - `excel_total = 26931.25`
  - `delta_total = -26931.25` (bloqueante)
- Al mismo tiempo detecta `14 partida(s)` normalizadas desde documento canonico.
- El flujo no materializa esas partidas en `session_line_items`, por lo que el calculo queda en cero.

## Impacto

- No se puede cerrar la cedula economica (Anexo 13) aunque exista Excel de costos.
- La generacion documental queda detenida en `ECONOMIC_GAP`.

## Hipotesis tecnica

1. El pipeline de ingestion Excel no mapea filas salariales/cargas a line items consumibles por el motor.
2. El validador de cuadratura compara contra `excel_total` pero el motor calcula sobre `session_line_items` vacio.
3. `ENABLE_BLOCK_RESOLUTION=false` impide resolucion masiva de precios por bloque desde API.

## Evidencia

- Mensaje de bloqueo:
  - "Detecte una diferencia de cuadratura entre tu Excel y el calculo del motor economico mayor a $0.01."
- `missing_price_count = 1`
- Alerta analista:
  - "no hay filas en session_line_items"

## Accion temporal para la prueba actual

- Se genero tabla minima de partidas en:
  - `backend/scratch/tabla_minima_partidas_vigilancia_issste_2024.csv`
- Objetivo: tener set minimo validable para captura/mapeo manual y destrabar corrida.

## Accion obligatoria post-prueba (pendiente de producto)

1. Implementar mapeador deterministico Excel -> `session_line_items` para perfiles de servicios (vigilancia).
2. Alinear `economic_normalizer` y `economic_calculator_engine` para consumir mismas claves canonicas.
3. Agregar regression test E2E:
   - carga Excel costos vigilancia
   - `line_items_count > 0`
   - `engine_total` ~= `excel_total` (tolerancia <= 0.01)
4. Definir estrategia de fallback cuando falten filas:
   - bloquear con mensaje accionable + template de columnas esperadas.

## Prioridad

- Prioridad: `P0` (bloquea cierre economico de licitacion vigente)
- Dueño sugerido: equipo backend economico / ingestion tabular
