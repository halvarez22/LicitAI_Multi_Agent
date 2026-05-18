# Tareas: fill-quality-gate-calibration

## Fase actual (spec + diseño)
- [x] Definir objetivos y métricas de calibración.
- [x] Diseñar runner de evaluación con ground truth.
- [x] Definir gobernanza de política versionada.
- [x] Definir criterios de go/no-go a enforce.

## Implementación (siguiente paso tras validación)
- [ ] Crear esquema `CalibrationCase` y dataset inicial etiquetado.
- [ ] Implementar `FillGateCalibrationRunner`.
- [ ] Implementar cálculo de matriz de confusión y métricas por regla.
- [ ] Versionar política de calibración (umbrales/severidades/allowlist).
- [ ] Emitir reporte técnico + resumen ejecutivo automático por corrida.

## Validación
- [ ] Ejecutar baseline con política actual (audit).
- [ ] Ejecutar al menos una iteración de tuning y comparar mejora.
- [ ] Documentar recomendación final (`audit`, `enforce parcial` o `enforce total`).
- [ ] Contrastar resultados con Antigravity.
