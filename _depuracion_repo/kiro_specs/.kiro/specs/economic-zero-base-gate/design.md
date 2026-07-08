# Diseño: Freno `total_base_cotizable`

## Verdad canónica

| Campo | Ubicación | Semántica |
|-------|-----------|-----------|
| `allow_zero_total_base_ack` | `session_state.economic_user_inputs` | Usuario (o integración) confirma que una oferta con subtotal cotizable ~0 es válida. |
| `allow_zero_total_base_ack` | `economic_proposal` task result | Copia al cerrar Fase 1 para que generación y writer no dependan solo de releer sesión. |

## Motor (`engine.py`)

- Nuevo parámetro opcional `allow_zero_total_base: bool = False` en `validate_economic_proposal`.
- Regla `total_base_cotizable` insertada tras `precios_positivos` para no mezclar responsabilidades.
- Umbral: `0.01` (un centavo MXN) como límite inferior operativo.

## Agente económico (`economic.py`)

- Lee `bool((session_state.get("economic_user_inputs") or {}).get("allow_zero_total_base_ack"))`.
- Pasa el flag al motor.
- Incluye el booleano en `final_result` y en payloads bloqueados cuando aplique.

## Revalidación (`service.py`)

- `_run_validation_for_payload` recibe `allow_zero_total_base` desde la sesión al refrescar.

## Items accionables (bloqueo)

- `_fallback_blocking_items_from_proposal` devuelve un ítem sintético con `row_index: 1` para `total_base_cotizable`, evitando que el filtro de anclas deje el bloqueo sin acción en chat.

## Writer (`economic_writer.py`)

- Tras normalizar `mapeo_items`, si `sum(importe) < 0.01` y no hay ack en `economic_data`, retornar `WAITING_FOR_DATA`.

## Política (`validation_policy_service.py`)

- Añadir `total_base_cotizable` a `_CRITICAL_NEVER_SKIP`.

## API HITL

- `POST /api/v1/sessions/{session_id}/economic-hitl/zero-total-base-ack` — cuerpo `{ "confirm": true, "reason": "..." }`; implementado en `backend/app/api/v1/routes/sessions.py`.
