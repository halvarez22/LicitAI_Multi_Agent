# Diseño: puente Orquestador/UI para gate documental

## Backend

- Nuevo helper en `orchestrator.py`:
  - `_document_quality_waiting_hints_from_output(res)` devuelve `{reason, metrics}` si existe.
- En la rama `generation` + `WAITING_FOR_DATA`, si hay hints de calidad:
  - agregarlos a `OrchestratorState.waiting_hints`;
  - persistir en sesión `last_document_quality_waiting_hints`.

## Frontend

- Nuevos detectores en `App.jsx`:
  - `orchestratorDataHasDocumentQualityGateBlocking(data)`.
- En `waiting_for_data`:
  - sintetizar `validationEvents` para `document_quality_gate_blocking` a partir de `missing`.
- Nuevo latch:
  - `documentQualityBlockingSessionLatch`.
- Render tarjeta de bloqueo de calidad documental con CTA de revalidación.

## Compatibilidad

- No altera contratos existentes (`economic_validation_blocking` mantiene comportamiento).
