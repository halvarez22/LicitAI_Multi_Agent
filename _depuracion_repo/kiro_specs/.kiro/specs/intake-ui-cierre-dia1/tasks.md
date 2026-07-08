# Tareas: intake-ui-cierre-dia1

## Fase actual (spec + diseño)
- [x] Definir requerimientos visuales de progreso intake.
- [x] Diseñar componente `IntakeProgressCard`.
- [x] Definir mapeo de datos backend -> UI.

## Implementación (siguiente paso tras validación)
- [ ] Crear `frontend/src/components/IntakeProgressCard.jsx`.
- [ ] Integrar estado `intakeUiSnapshot` en `frontend/src/App.jsx`.
- [ ] Hidratar snapshot desde respuestas chatbot (`progress_*`).
- [ ] Renderizar card en panel de asistente.
- [ ] Aplicar copy ejecutivo y estados visuales (active/risk/completed).

## Validación
- [ ] Prueba manual: saludo proactivo -> opt-in -> ver barra X/N.
- [ ] Prueba manual: refresh en mitad de intake -> badge “Reanudado”.
- [ ] Prueba manual: bloqueantes > 0 -> estado visual de atención.
- [ ] Validar que no se rompe flujo legacy ni RAG.
