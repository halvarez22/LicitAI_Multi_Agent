# Requisitos: Freno de importe base cotizable (propuesta económica)

## Contexto

La Fase 1 económica puede marcar `SUCCESS` con `total_base` en cero cuando solo existen renglones exentos (p. ej. supervisor sin costo) o cuando la validación `precios_positivos` no aplica ítems bloqueantes. El `EconomicWriterAgent` materializa Excel/Word con totales en cero sin valor de negocio.

## Requisitos funcionales

### R1 — Bloqueo explícito

- **DADO** una propuesta con `total_base` estrictamente menor a **0,01** en la moneda de la sesión (MXN por defecto)
- **Y** no existe confirmación HITL de oferta sin importe base
- **ENTONCES** el motor `validate_economic_proposal` debe registrar la regla `total_base_cotizable` en estado **blocking** y añadir un mensaje en `blocking_issues`.

### R2 — Confirmación HITL (canal sesión)

- **DADO** `session_state.economic_user_inputs.allow_zero_total_base_ack == True` (booleano explícito)
- **ENTONCES** la regla `total_base_cotizable` debe evaluarse en **ok** aunque `total_base < 0,01`, dejando trazabilidad de que la confirmación estuvo activa.
- **API (v1):** `POST /sessions/{session_id}/economic-hitl/zero-total-base-ack` con cuerpo `{ "confirm": true, "reason": "..." }` persiste el ack y opcionalmente refresca validaciones si existe `economic_proposal`.

### R3 — Persistencia para generación

- **DADO** un cierre económico `complete` del `EconomicAgent`
- **ENTONCES** el resultado persistido en `economic_proposal` debe incluir `allow_zero_total_base_ack` (booleano) coherente con la sesión al momento del cálculo.

### R4 — Defensa en profundidad (writer)

- **DADO** que el `EconomicWriterAgent` va a escribir archivos
- **Y** la suma de importes de línea normalizados es `< 0,01`
- **Y** `allow_zero_total_base_ack` no es verdadero en el payload económico
- **ENTONCES** el agente debe devolver `WAITING_FOR_DATA` (no `SUCCESS` con archivos vacíos de negocio).

### R5 — UX y política

- Debe existir entrada en `validation_mapping.json` para `error_type` `total_base_cotizable` con mensaje claro: capturar precios o confirmar explícitamente oferta sin importe base vía flujo HITL.
- La política dinámica debe tratar `total_base_cotizable` como regla **no omitible** con justificación genérica (misma familia que precios críticos).

## Fuera de alcance

- Detección NL en chat para activar el ack (puede añadirse después); v1 usa sesión + endpoint HITL documentado en R2.
