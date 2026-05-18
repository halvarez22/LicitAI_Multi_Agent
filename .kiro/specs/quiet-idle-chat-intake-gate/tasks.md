# Plan de Implementación: Quiet Idle Chat Intake Gate

## Fase 0 — Aprobación de diseño
- [ ] Validar reglas de activación de `has_real_work_context`.
- [ ] Aprobar copy neutral de estado idle.

## Fase 1 — Backend gate (chatbot)
- [ ] Implementar helper `has_real_work_context(session_state, company_id)` en `chatbot_rag.py`.
- [ ] Aplicar gate antes de:
  - promoción de `pending_questions`,
  - intake proactivo,
  - mensajes de bootstrap que sugieren análisis en curso.
- [ ] Incluir campos aditivos en respuesta (`intake_active`, `activity_state`).

## Fase 2 — Frontend gate (render intake)
- [ ] Ajustar `updateIntakeUiSnapshotFromBotData` para ignorar snapshots sin `intake_active`.
- [ ] Render condicional de `IntakeProgressCard` basado en señal activa real.
- [ ] Revisar flujo bootstrap para evitar mensajes de ruido en sesión vacía.

## Fase 3 — Pruebas
- [ ] Unit tests backend:
  - sesión nueva sin fuentes => modo idle neutral,
  - sesión con pendientes reales => intake visible.
- [ ] Verificación frontend:
  - no render Intake card en sesión vacía,
  - render correcto al activar contexto real.
- [ ] Smoke E2E manual:
  - crear licitación limpia,
  - seleccionar empresa,
  - comprobar ausencia de ruido,
  - cargar/analisar fuentes y comprobar activación correcta.

## Fase 4 — Cierre
- [ ] Registrar evidencia de comportamiento antes/después.
- [ ] Confirmar no regresión en flujos de generación/go-no-go.
