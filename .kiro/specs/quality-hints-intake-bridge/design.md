# Diseño: Puente de Hints de Calidad a Intake/Chat

## Alcance

Diseño de integración para convertir bloqueos de calidad en preguntas de resolución dentro del flujo de intake/chat.

Componentes objetivo:
- `backend/app/agents/intake_planner.py`
- `backend/app/agents/chatbot_rag.py`
- `backend/app/agents/orchestrator.py` (solo acople de datos, sin relajar políticas)

## Arquitectura propuesta

### 1) Fuente de verdad de bloqueo

Se mantiene como hoy:
- `orchestrator` persiste hints en sesión:
  - `last_document_quality_waiting_hints`
  - `last_document_fill_quality_waiting_hints`

No se modifica la lógica de bloqueo; solo el consumo de esos hints.

### 2) IntakePlanner: nueva extracción de preguntas

Agregar:
- `_questions_from_quality_hints(session_state: Dict[str, Any]) -> List[Dict[str, Any]]`

Flujo:
1. leer hints de calidad/fill,
2. normalizar estructura (`issues`, `metrics`, `reason`),
3. mapear a preguntas de negocio,
4. inyectar a pipeline existente (dedupe + sort + summary).

## Mapeo sugerido hint -> pregunta

### A) `document_quality_gate` (clasificación/alcance documental)

- `error_type`: `document_quality_gate` / `policy_miss` / clasificación ambigua  
  Pregunta:
  - "Detecté un requisito con clasificación ambigua. ¿Debo tratarlo como documento a generar, a presentar físicamente o solo informativo?"
  `field_target`: `quality.classification.<doc_or_req_id>`
  `priority`: `BLOQUEANTE`

### B) `document_fill_quality_gate` (llenado)

- `required_field_missing`  
  Pregunta:
  - "Falta un dato crítico en `<documento>` (`<campo>`). ¿Cuál es el valor correcto?"

- `source_confidence_insufficient`  
  Pregunta:
  - "El dato `<campo>` en `<documento>` no tiene evidencia suficiente. ¿Me confirmas el valor para continuar?"

- `cross_field_inconsistency`  
  Pregunta:
  - "Encontré inconsistencia entre campos relacionados en `<documento>`. ¿Me confirmas el valor correcto para cerrar la propuesta?"

## Contrato de pendiente sugerido

```json
{
  "type": "quality_validation_blocking",
  "question": "¿Debo generar este anexo o es informativo?",
  "field": "quality.classification.anexo_7",
  "priority": "BLOQUEANTE",
  "source": "document_quality_gate",
  "error_type": "policy_miss",
  "context": {
    "document_id": "ANEXO_7.docx",
    "field_key": "tipo_accion",
    "hint_source": "last_document_quality_waiting_hints"
  }
}
```

## ChatbotRAG: comportamiento esperado

Cuando existan pendientes `quality_validation_blocking`:

1. priorizar la pregunta en respuesta,
2. mostrar copy claro (sin código interno),
3. mantener `progress_*`,
4. tras respuesta, persistir dato/decisión y disparar ruta de revalidación.

## Revalidación y continuidad

Regla:
- respuesta de usuario -> persistencia -> revalidación del gate afectado.

Resultados:
- si desbloquea: continuar etapa de generación.
- si no desbloquea: producir siguiente pregunta concreta (no repetir literal).

## Riesgos y mitigaciones

- Riesgo: sobrecarga de preguntas simultáneas.
  - Mitigación: agrupar por documento y priorizar una acción por turno.

- Riesgo: copy demasiado técnico.
  - Mitigación: capa de traducción UX por `error_type` + plantillas de lenguaje de negocio.

- Riesgo: duplicidad con pendientes legacy.
  - Mitigación: dedupe por `field_target` + `sim_key`.

## Criterios de diseño aprobables

- Bloqueo de calidad siempre se convierte en al menos una pregunta resoluble.
- El usuario entiende qué decisión tomar sin leer términos internos.
- El flujo conserva seguridad: no hay bypass de gates críticos.
