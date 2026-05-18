# Requisitos: Integración gate documental en Orquestador/UI

## Objetivo

Cuando `technical_writer` o `formats` bloqueen por `document_quality_gate`, el orquestador y la UI deben exponerlo claramente con hints accionables y tarjetas de validación.

## Requisitos funcionales

- R1: El orquestador debe extraer `document_quality_gate` desde `AgentOutput.data` y persistirlo como `waiting_hints`.
- R2: En respuesta `waiting_for_data`, la UI debe mostrar alerta tipo `block` para `document_quality_gate_blocking` aunque no vengan `validation_events`.
- R3: La UI debe activar un latch visual dedicado para bloqueo de calidad documental y ofrecer revalidación.
- R4: El mapping de validación debe incluir `error_type=document_quality_gate` para consistencia semántica.
