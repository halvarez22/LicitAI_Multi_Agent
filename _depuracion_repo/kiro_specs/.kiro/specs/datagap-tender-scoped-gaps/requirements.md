# Requisitos: brechas de perfil ancladas a la licitación

## Problema

El `DataGapAgent` evaluaba **todos** los campos de `FIELD_DEFINITIONS` en cada sesión. Eso provocaba preguntas HITL genéricas (p. ej. número de empleados, años de experiencia) aunque los requisitos extraídos de **esta** licitación no los mencionaran, mezclando un checklist corporativo global con el flujo por instrumento.

## Objetivo

Las preguntas por datos faltantes deben limitarse a:

1. **Perfil mínimo bloqueante** — campos en `BLOCKING_FIELDS` necesarios para generación/empaquetado coherente (`rfc`, `razon_social`, `domicilio_fiscal`, `representante_legal`).
2. **Datos exigidos por esta licitación** — campos de perfil que correspondan a **slots inferidos** desde los requisitos de `compliance_master_list` (administrativo + técnico), vía `SlotInferenceService` y `INFERRED_TO_PROFILE_MAP`.

## Criterios de aceptación

- **R1:** Si `compliance_master_list` no sugiere el slot `employee_count` (ni equivalente), el agente **no** debe encolar `numero_empleados` por el solo hecho de estar vacío en `master_profile`.
- **R2:** Los cuatro bloqueantes se siguen evaluando siempre; si faltan o son inválidos tras RAG, se encolan con `is_blocking=True` y el estado puede ser `WAITING_FOR_DATA`.
- **R3:** Si un requisito de compliance infiere p. ej. `email`, se evalúa `email` aunque no sea bloqueante; si falta, se encola con `is_blocking=False`.
- **R4:** La auto-rellenación RAG y `_is_data_valid` no cambian de comportamiento para los campos que **sí** entren en el conjunto activo.
- **R5:** La caché `compliance_slot_cache` por requisito se mantiene para no repetir inferencia.

## Fuera de alcance (esta iteración)

- Ampliar vocabulario de slots o mapeos nuevos en `slot_inference`.
- Cambiar política de `ChatbotRAG` salvo coherencia con la lista `missing` ya reducida.
- Pantalla de “completar expediente corporativo” fuera de sesión de licitación.

## Relación con specs anteriores

`datagap-enqueue-all-missing` exigía encolar **todo** faltante del checklist. Este spec **restringe qué campos forman parte del checklist evaluable** en contexto de sesión de licitación; una vez en el conjunto activo, sigue aplicando el encolado de faltantes (bloqueante vs informativo) ya implementado.
