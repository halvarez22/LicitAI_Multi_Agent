# Fase 4 — Feedback Humano en el Bucle (HITL)

## Introducción
Esta fase permite a los usuarios corregir las extracciones realizadas por el sistema multi-agente, recolectando datos valiosos para analítica y aprendizaje futuro (Fase 5+).

## Modelo de Datos
Tabla: `extraction_feedback` (PostgreSQL)

| Campo | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | UUID (PK) | Identificador único del feedback. |
| `session_id` | String | Relación con la licitación actual. |
| `company_id` | String | Relación opcional con la empresa participante. |
| `agent_id` | String | Agente que generó la extracción (analyst, compliance, etc.). |
| `pipeline_stage` | String | Etapa de la pipeline donde se generó. |
| `entity_ref` | String | Referencia estable (ej: REQ-01, RFC). |
| `was_correct` | Boolean | `true` (correcto), `false` (incorrecto), `null` (parcial). |
| `user_correction`| Text | El valor sugerido por el humano. |
| `correction_type`| Enum | `value_error`, `missing`, `false_positive`, `other`. |

## Endpoints API
Ruta Base: `/api/v1/feedback`

### 1. Crear Feedback
`POST /api/v1/feedback`
```json
{
  "session_id": "893d-...",
  "agent_id": "analyst",
  "pipeline_stage": "analysis",
  "entity_type": "requirement",
  "entity_ref": "AD-01",
  "was_correct": false,
  "user_correction": "Debe decir: RFC válido",
  "correction_type": "value_error",
  "user_comment": "La extracción omitió la sección de validación."
}
```

### 2. Listar Feedback por Sesión
`GET /api/v1/feedback/session/{session_id}`

## Lógica de Negocio y Validación
- **Validation Rule**: Si `was_correct` es `false`, es obligatorio proveer o bien una `user_correction`, o un `correction_type != other` junto con un `user_comment`.
- **Feature Flags**: El API y la UI se controlan mediante `FEEDBACK_API_ENABLED` y `FEEDBACK_UI_ENABLED`.

## Límites Explícitos
- **No RLHF**: Esta fase solo **relecta** el feedback. No se ajustan las prompts de los agentes automáticamente en caliente.
- **Trazabilidad**: Se guardan las versiones de los prompts y agentes (`prompt_version`) para asegurar que el feedback actúe como un "Gold Standard" histórico fiel.
