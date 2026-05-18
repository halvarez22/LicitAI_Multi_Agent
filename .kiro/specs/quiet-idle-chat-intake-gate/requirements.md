# Requisitos: Quiet Idle Chat Intake Gate

## Contexto
En sesiones recién creadas (sin fuentes cargadas, sin análisis ejecutado y/o sin empresa válida seleccionada), el asistente conversacional está mostrando mensajes y estados de intake que el usuario percibe como ruido o eventos no ocurridos.

Esto genera fricción UX y sensación de inconsistencia ("aparecen cosas sin haber hecho nada").

## Objetivo
Asegurar que el chat y los indicadores de intake solo muestren información cuando exista actividad real del proceso o evidencia verificable en sesión.

## Requisitos funcionales

### R1 — Silencio en estado inactivo real
- Si la sesión no tiene fuentes analizadas ni análisis ejecutado, el chat no debe mostrar pendientes ni progreso de intake.
- En ese estado, el asistente debe mostrar solo copy neutral de arranque (sin afirmar que ya analiza bases).

### R2 — Gate de activación de intake
- `pending_questions` e `intake_progress` solo deben mostrarse cuando exista al menos una condición de activación:
  - empresa válida seleccionada y/o
  - fuentes cargadas/analizadas y/o
  - resultado previo de análisis/go-no-go/gates.

### R3 — Mensajería veraz
- El texto del asistente debe reflejar únicamente hechos actuales.
- Se prohíbe copy que implique análisis en curso/completado si no hay evidencia en sesión.

### R4 — UI sin ruido residual
- `IntakeProgressCard` no debe renderizarse cuando no existe estado activo real de intake.
- Mensajes de empresa inválida solo deben aparecer cuando el usuario intente acción que requiera empresa.

### R5 — Compatibilidad de flujo
- No romper rutas existentes de:
  - captura de datos faltantes,
  - quality-hints bridge,
  - go/no-go y generación.

## Requisitos no funcionales

### N1 — Trazabilidad
- Registrar en sesión señales mínimas que expliquen por qué se activó/no activó intake.

### N2 — No regresión UX
- Mantener experiencia actual cuando sí existe actividad real (no degradar rescates y guidance).

## Criterios de aceptación
- Crear sesión nueva sin fuentes: el chat permanece en modo neutral sin intake visible.
- Seleccionar empresa sin análisis de bases: no debe aparecer progreso de intake ficticio.
- Cargar/analisar fuentes: intake puede activarse si hay pendientes reales.
- No aparecen mensajes de "ya estoy analizando el pliego" en ausencia de análisis real.
