# Tareas: blindaje-sectorial-analyst-dia2

## Fase actual (spec + diseño)
- [x] Definir contrato `sector_classification` en salida del Analyst.
- [x] Diseñar pipeline hybrid (rule-based + llm-assisted + resolución conservadora).
- [x] Definir catálogo inicial de señales por sector (v1).
- [x] Definir reglas de decisión (`indeterminado` / `mixto`).

## Implementación (siguiente paso tras validación)
- [ ] Crear helper interno de extracción de señales sectoriales en `analyst.py`.
- [ ] Implementar función de scoring y resolución canónica.
- [ ] Integrar evidencia textual (`snippet`, `signal_code`, `weight`, `source_hint`).
- [ ] Ajustar prompt del Analyst para sector + evidencias literales.
- [ ] Persistir `sector_classification` en `extracted_data` sin romper campos previos.
- [ ] Exponer telemetría mínima en logs estructurados.

## Pruebas
- [ ] Unit test: clasificación `obra_publica` con señales fuertes.
- [ ] Unit test: caso ambiguo -> `mixto`.
- [ ] Unit test: evidencia insuficiente -> `indeterminado`.
- [ ] Regression test: no degradar extracción existente (cronograma/solvencias).
- [ ] Smoke test: `IntakePlanner` sigue operando con el nuevo campo aditivo.
