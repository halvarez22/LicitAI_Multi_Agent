# Diseño: UI Intake Día 1 (Progress + Status Card)

## Alcance

Cambios frontend exclusivamente (sin alterar lógica core backend):
- `frontend/src/App.jsx`
- nuevo componente visual en `frontend/src/components/` para estado de intake.

## Arquitectura UI propuesta

### Componente nuevo: `IntakeProgressCard`

Props sugeridas:
- `progressCurrent: number`
- `progressTotal: number`
- `progressLabel: string`
- `blockingCount: number`
- `remainingCount: number`
- `isResumed: boolean`
- `auditMode: boolean`

Render:
1. Encabezado ejecutivo:
   - “Estado de Intake”
   - badge `Reanudado` (si aplica)
2. Barra visual de progreso (%)
3. Métricas rápidas:
   - `Bloqueantes: X`
   - `Pendientes: Y`
4. Pie contextual:
   - “Prioriza bloqueantes para habilitar generación segura.”

## Fuente de datos y mapeo

### Prioridad de lectura en UI
1. Último mensaje bot con `progress_current/total/label`.
2. Estado de sesión recuperado (`intake_plan.summary`).
3. Fallback a cálculo local de cola visible si no hay contrato.

### Reglas de cálculo
- `percent = round((progressCurrent / progressTotal) * 100)` con clamp `[0,100]`.
- `remainingCount = max(progressTotal - progressCurrent, 0)` salvo valor explícito de backend.

## Integración en `App.jsx`

1. Nuevo estado local:
   - `intakeUiSnapshot`
2. Hook de actualización:
   - cada vez que llegue respuesta de chatbot, si trae `progress_*`, actualizar snapshot.
3. Hidratación inicial:
   - al cargar sesión, intentar poblar desde respuesta de dictamen/sesión si existe.
4. Render:
   - mostrar `IntakeProgressCard` sobre el panel de mensajes (debajo de encabezado del asistente).

## UX copy (tono consultor senior)

Ejemplos:
- Header: “Estado de Intake”
- Contexto:
  - “Tenemos puntos de integridad pendientes antes de cerrar propuesta.”
  - “Avance estable: continuemos con la siguiente pregunta.”

Evitar términos:
- “error”, “fallo”, “se rompió”.

## Estados visuales

1. **Idle**
   - sin intake activo → no mostrar card.
2. **Active**
   - progreso visible + pendientes.
3. **Risk**
   - `blockingCount > 0` → borde/ícono de atención.
4. **Completed**
   - `progressCurrent == progressTotal` y no pendientes.

## Riesgos y mitigaciones

- Riesgo: divergencia entre card y chat.
  - Mitigación: card solo refleja contrato backend, no lógica paralela.
- Riesgo: snapshot viejo tras cambio de sesión.
  - Mitigación: reset completo de estado visual al cambiar `sessionId`.

## Telemetría sugerida

- `ui_intake_card_shown`
- `ui_intake_progress_updated`
- `ui_intake_resumed_badge_shown`

## Criterios de diseño aprobables

- El usuario visualiza avance y riesgo en menos de 2 segundos de lectura.
- El componente funciona igual con flujo intake planner y legacy.
- No requiere tocar contratos backend para Día 1.
