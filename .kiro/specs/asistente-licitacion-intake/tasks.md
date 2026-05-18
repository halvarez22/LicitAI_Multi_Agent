# Tareas: asistente-licitacion-intake

## Fase 0 — Especificación y diseño (completada)
- [x] Completar requisitos funcionales/no funcionales.
- [x] Definir diseño de `IntakePlannerAgent`.
- [x] Definir contratos I/O y estrategia de rollout.

## Fase 1 — Backend core
- [ ] Extender Analyst con campos estructurados nuevos.
- [ ] Implementar `IntakePlannerAgent`.
- [ ] Integrar ejecución en orquestador (modo shadow inicialmente).
- [ ] Persistir `intake_plan` e `intake_progress` en sesión.

## Fase 2 — Chat proactivo
- [ ] Integrar trigger proactivo con opt-in en `ChatbotRAGAgent`.
- [ ] Implementar navegación de preguntas priorizadas.
- [ ] Guardar respuestas en `master_profile`/contexto licitación.

## Fase 3 — Compatibilidad y UX
- [ ] Conectar plan con UI (resumen y progreso).
- [ ] Mantener compatibilidad con `pending_questions` legacy.
- [ ] Exponer `provenance_ui` homogénea chat/panel.

## Fase 4 — QA y hardening
- [ ] Pruebas unitarias de priorización/deduplicación.
- [ ] Pruebas de integración Orchestrator + Chatbot.
- [ ] Pruebas E2E UI: análisis -> plan -> resolución -> generación.
