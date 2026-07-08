# Tareas: quality-hints-intake-bridge

## Fase actual (spec + diseño)
- [x] Definir alcance de integración quality hints -> intake/chat.
- [x] Diseñar mapeo de `error_type` a preguntas de negocio.
- [x] Definir contrato de pendiente `quality_validation_blocking`.

## Implementación (siguiente paso tras validación)
- [ ] Implementar `_questions_from_quality_hints` en `IntakePlannerAgent`.
- [ ] Integrar lectura de `last_document_quality_waiting_hints` y `last_document_fill_quality_waiting_hints`.
- [ ] Inyectar preguntas de calidad al pipeline de dedupe/sort/summary del planner.
- [ ] Ajustar `ChatbotRAGAgent` para priorizar y resolver `quality_validation_blocking`.
- [ ] Conectar revalidación tras respuesta de usuario.

## Pruebas
- [ ] Unit test: planner genera preguntas desde `document_quality_waiting_hints`.
- [ ] Unit test: planner genera preguntas desde `document_fill_quality_waiting_hints`.
- [ ] Unit test: dedupe evita duplicados calidad + pendientes legacy.
- [ ] Integración: bloqueo en generación -> pregunta de desbloqueo visible en chat.
- [ ] Integración: respuesta de usuario -> revalidación -> avance o siguiente pregunta concreta.
