# Requisitos: Cierre UI Intake (Día 1)

## Contexto

El backend ya expone progreso de intake (`progress_current`, `progress_total`, `progress_label`) y estado de reanudación robusto.
Falta cerrar la experiencia visual para que operación vea claramente:

1. avance real del intake,
2. riesgo actual (bloqueantes vs pendientes),
3. capacidad de retomar donde quedó.

## Objetivo

Implementar en frontend una capa visual de alto impacto y bajo riesgo:
- **Barra de progreso** del intake,
- **Status card** con resumen ejecutivo,
- **estado de reanudación** consistente tras refresh.

## Requisitos funcionales

### R1 — Barra de progreso visible
- Mostrar barra cuando exista intake activo o oferta proactiva.
- Debe usar solo contrato backend:
  - `progress_current`
  - `progress_total`
  - `progress_label`
- Si `progress_total = 0`, ocultar barra.

### R2 — Status card ejecutivo
- Mostrar tarjeta “Estado de Intake” con:
  - bloqueantes detectados,
  - pendientes restantes,
  - mensaje de orientación (“resolver bloqueantes primero”).
- Fuente de datos:
  - `intake_plan.summary` cuando esté disponible,
  - fallback a conteo de cola activa.

### R3 — Estado de reanudación visual
- Tras refresh/reingreso, UI debe reflejar:
  - pregunta actual,
  - progreso correcto,
  - badge “Reanudado” si aplica.
- No debe reiniciar visualmente a “0 de N” si backend ya está en medio del flujo.

### R4 — Integración con panel de chat
- El bloque visual debe convivir con mensajes actuales sin romper layout.
- Debe mostrarse tanto en flujo intake planner como en pending legacy.

### R5 — Señal no bloqueante en modo audit
- Si el sistema está en modo `audit`, mostrar etiqueta “Validación en modo auditoría”.
- No confundir con bloqueo real.

## Requisitos no funcionales

### N1 — Sincronía backend/frontend
- La UI no debe recalcular negocio de prioridades; solo representar estado recibido.

### N2 — Performance UX
- Render incremental sin reflow excesivo del panel de chat.

### N3 — Accesibilidad básica
- Barra con `aria-label` y texto equivalente visible.

## Criterios de aceptación

- Usuario siempre sabe cuántas preguntas faltan.
- Usuario identifica si hay bloqueantes sin leer logs.
- Tras refrescar, la UI retoma el mismo punto sin confusión.
- No se rompe ningún flujo actual de chat/RAG/captura.
