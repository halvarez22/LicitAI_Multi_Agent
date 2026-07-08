# Tareas: asistente-licitacion-intake-fase-2_5

## Fase actual (spec + diseño)
- [x] Definir requerimientos UX de copy/progreso/reanudación.
- [x] Diseñar contrato de respuesta con progreso.
- [x] Diseñar estrategia de resume por `question_id` + fallback.

## Implementación (siguiente paso tras validación)
- [ ] Implementar helpers de progreso/copy/resume en `chatbot_rag.py`.
- [ ] Persistir y actualizar `intake_progress` de forma consistente.
- [ ] Incluir `progress_label` en respuestas de captura/reanudación.
- [ ] Ajustar copy ejecutivo en oferta, prompt, resume y cierre.

## Validación técnica
- [ ] Tests unitarios de `compute_progress` y `resolve_resume_pointer`.
- [ ] Tests de integración chatbot:
  - [ ] muestra “Pregunta X de N”
  - [ ] retoma exacto tras refresh
  - [ ] no rompe flujo legacy
- [ ] Regresión completa `test_chatbot_rag_behavior.py`.
