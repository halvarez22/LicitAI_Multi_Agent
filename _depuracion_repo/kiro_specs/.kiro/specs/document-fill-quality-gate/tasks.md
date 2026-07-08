# Tareas: document-fill-quality-gate

## Día 1 — Cierre de especificación (completado)
- [x] Definir alcance del Punto 2 (llenado correcto) separado del Punto 1.
- [x] Definir contrato de hallazgos (`issues[]`) y severidades.
- [x] Definir arquitectura del gate post-generación.
- [x] Definir plan de rollout `audit/enforce`.

## Día 2 — Implementación (pendiente)
- [ ] Implementar `DocumentFillQualityGateService` con reglas base.
- [ ] Implementar `DocumentFieldPolicyRegistry` versionado.
- [ ] Integrar gate en `technical_writer`, `formats`, `economic_writer`.
- [ ] Integrar persistencia de hints en orquestador/sesión.
- [ ] Agregar `validation_mapping` para nuevos `error_type`.

## Día 3 — Validación técnica (pendiente)
- [ ] Pruebas unitarias del gate por regla y severidad.
- [ ] Pruebas de integración por writer.
- [ ] Pruebas de regresión de latencia y estabilidad.

## Día 4 — Contraste y UAT (pendiente)
- [ ] Contrastar diseño/implementación con Gemini.
- [ ] Ejecutar checklist de evaluación de copiloto.
- [ ] Revalidar flujo end-to-end desde UI (análisis → generación → bloqueos/acciones).
