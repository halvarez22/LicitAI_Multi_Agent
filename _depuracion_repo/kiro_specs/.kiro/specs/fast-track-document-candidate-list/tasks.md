# Plan de Implementación: fast-track-document-candidate-list

## Fase 0 — Alineación (completado)
- [x] Definir objetivos de negocio y criterio operativo para 8GB VRAM.
- [x] Definir contrato candidato + confirmación humana + gates finales.

## Fase 1 — Backend Candidate List
- [ ] Implementar constructor `candidate_document_list` a partir de `ComplianceAgent`.
- [ ] Agregar consolidación/dedupe y `candidate_summary`.
- [ ] Persistir `document_candidates_v1` en sesión.

## Fase 2 — HITL Confirmación
- [ ] Crear endpoint/flujo para guardar overrides por documento.
- [ ] Persistir `document_candidates_user_overrides`.
- [ ] Construir `document_candidates_final` (regla de precedencia).

## Fase 3 — Chat/UX de Confirmación Rápida
- [ ] Integrar en `ChatbotRAGAgent` prompts de confirmación por lotes.
- [ ] Implementar copy no técnico y accionable.
- [ ] Exponer `needs_human_confirmation` y `unresolved_count`.

## Fase 4 — Integración con Writers y Gates
- [ ] Hacer que writers consuman `document_candidates_final`.
- [ ] Excluir explícitamente `presentar_fisico`/`informativo`/`no_aplica`.
- [ ] Mantener gates finales críticos activos.

## Fase 5 — Pruebas técnicas
- [ ] Unit tests de candidate builder (incluye no-aplica).
- [ ] Unit tests de precedencia `user_override > auto`.
- [ ] Integration tests de generación con lista final.
- [ ] Regression tests para flujo legacy con flag apagado.

## Fase 6 — UAT UI (prueba de fuego)
- [ ] Ejecutar corrida real en UI con bases reales.
- [ ] Medir tiempo a lista candidata y tiempo a generación.
- [ ] Emitir dictamen GO / GO condicionado / NO GO.
