# QA Checklist - Validaciones Humanas v3

## A. Reglas de Severidad
- [ ] `block` impide finalizar propuesta.
- [ ] `warn` permite continuar solo tras `acknowledged=true`.
- [ ] `info` nunca bloquea flujo; solo panel lateral.

## B. Mensajeria Humana
- [ ] Ningun mensaje muestra `error_type` crudo al usuario final.
- [ ] Cada alerta renderiza: `title`, `user_message`, accion recomendada, `impact`.
- [ ] Concepto/campo afectado visible cuando existe en `context`.

## C. Acciones UI
- [ ] `primary_action` navega o ejecuta flujo correcto.
- [ ] `secondary_action` respeta politica (`continue_with_warning` solo en `warn`/`info`).
- [ ] Si `requires_justification=true`, bloquea avance hasta ingresar texto.

## D. Persistencia
- [ ] `acknowledged_warnings` sobrevive a refresh/reload.
- [ ] Justificaciones se guardan con `timestamp` y `session_id`.
- [ ] Al resolver `block`, se elimina de `blocked_until_resolved`.

## E. Politica por Convocatoria
- [ ] `allow_skip_with_justification=false` -> `block` se mantiene.
- [ ] `allow_skip_with_justification=true` -> `block` baja a `warn` + justificacion obligatoria.
- [ ] Politica se evalua por `tender_id`, no global.

## F. Telemetria Minima
- [ ] `validation_triggered` emite `{error_type, severity, session_id}`.
- [ ] `warning_acknowledged` registra `resolution_time_ms`.
- [ ] `block_resolved` registra `clicks_to_fix` y `resolution_time_ms`.
- [ ] `justification_submitted` guarda `item_id` y `length_chars`.

## G. Casos Borde
- [ ] Sesion expirada + restauracion mantiene validaciones pendientes.
- [ ] Multiples advertencias no sobrescriben `acknowledged` previos.
- [ ] Rollback/Undo restaura estado de validacion anterior correctamente.
