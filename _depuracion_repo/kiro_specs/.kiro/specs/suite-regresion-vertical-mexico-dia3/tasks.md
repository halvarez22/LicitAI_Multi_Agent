# Tareas: suite-regresion-vertical-mexico-dia3

## Fase actual (spec + diseño)
- [x] Definir cobertura mínima de 4 verticales.
- [x] Diseñar contrato de fixture y runner paramétrico.
- [x] Definir matriz inicial de señales obligatorias por vertical.

## Implementación (siguiente paso tras validación)
- [ ] Crear carpeta `backend/tests/fixtures/vertical_mexico/`.
- [ ] Crear 4 fixtures iniciales (`obra_publica`, `salud`, `adquisiciones`, `servicios`).
- [ ] Implementar `test_sector_vertical_mexico_suite.py` con parametrización.
- [ ] Agregar smoke de contrato base del analyst en la misma suite o archivo auxiliar.
- [ ] Generar resumen por caso (log estructurado o salida compacta en pytest).

## Validación
- [ ] Ejecutar suite vertical completa local.
- [ ] Ejecutar regresión corta del Analyst (`test_analyst_behavior.py` + sector tests).
- [ ] Documentar resultados (pass/fail + señales faltantes) para calibración Día 4.
