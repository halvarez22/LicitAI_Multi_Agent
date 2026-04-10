# INSTRUCTIONS - Engineering Operating Rules

## Objetivo
Mantener una base de software robusta, predecible y auditable en todos los proyectos.

## Reglas duras
1. No merge a `main` sin pasar CI.
2. Contratos de entrada/salida explícitos (tipado y validación).
3. Cambios pequeños, reversibles y con evidencia de prueba.
4. No exponer detalles internos sensibles en respuestas HTTP.

## Diseño y mantenimiento
- Separar responsabilidades por módulos.
- Evitar refactors de gran alcance en ventanas de release.
- Preferir compatibilidad hacia atrás en integraciones activas.

## Verificación obligatoria
- Ejecutar pruebas focalizadas del área tocada.
- Validar que no se rompieron contratos públicos.
- Registrar decisiones relevantes en `MEMORY.md`.
