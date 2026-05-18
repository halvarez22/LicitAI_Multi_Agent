# Requisitos: Panel de diagnóstico de calidad documental

## Objetivo

Mostrar en UI un diagnóstico explícito del gate documental para que operación entienda por qué se bloqueó y qué corregir.

## Requisitos funcionales

- R1: Exponer en UI `reason` y `metrics` del gate (cuando existan).
- R2: Semáforo visual (`bloqueado` / `estable`) con recomendaciones.
- R3: Botón de revalidación reutilizando flujo actual.
- R4: Disponible en sección de herramientas de sesión (no solo en chat derecho).
