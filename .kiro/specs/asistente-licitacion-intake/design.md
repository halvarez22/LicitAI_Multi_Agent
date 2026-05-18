# Diseño: Asistente de Intake para Licitación

## Objetivo de diseño

Pasar de flujo reactivo (bloqueo cuando falta dato) a flujo proactivo (plan guiado previo a generación), manteniendo compatibilidad con arquitectura actual.

## Arquitectura propuesta

### Componentes

1. **Analyst Extension Layer**
   - Enriquecer salida de `analyst.py` con solvencias y condiciones contractuales.

2. **IntakePlannerAgent (nuevo)**
   - Archivo propuesto: `backend/app/agents/intake_planner.py`
   - Rol: agregador, normalizador y priorizador.
   - No reemplaza análisis legal/técnico ni semáforo GoNoGo.

3. **Intake Session Bridge**
   - Persistencia en `session_state`:
     - `intake_plan`
     - `intake_progress`
     - `intake_last_updated_at`

4. **Chatbot Proactive Orchestrator**
   - Extiende `chatbot_rag.py` para disparar saludo proactivo con consentimiento.

## Contratos de entrada y salida

### Entrada `IntakePlannerAgent`

```json
{
  "session_id": "string",
  "company_id": "string",
  "analysis": {},
  "compliance": {},
  "go_no_go": {},
  "master_profile": {},
  "pending_questions_legacy": []
}
```

### Salida `IntakePlannerAgent`

```json
{
  "plan_version": "1.0.0",
  "summary": {
    "blocking_count": 0,
    "critical_count": 0,
    "important_count": 0,
    "complementary_count": 0
  },
  "questions": [
    {
      "question_id": "INTAKE-B-001",
      "question_type": "B",
      "priority": "BLOQUEANTE",
      "blocking": true,
      "question": "Las bases exigen capital minimo de $500,000. Cual es tu capital contable vigente?",
      "field_target": "solvencia.capital_contable",
      "required_evidence": "estado_financiero_auditado",
      "provenance_ui": {
        "source": "analyst+go_no_go",
        "confidence": 0.92,
        "reason": "knockout_detected"
      }
    }
  ]
}
```

## Lógica de priorización

1. `BLOQUEANTE`
   - GoNoGo `is_knockout=true`
   - Compliance `causas_desechamiento` activas
2. `CRITICO`
   - Solvencia legal/económica/técnica requerida por bases
3. `IMPORTANTE`
   - Penalizaciones, pagos, garantías contractuales
4. `COMPLEMENTARIO`
   - Campos de perfil no bloqueantes

## Deduplicación

- Normalizar por `field_target` + semántica de pregunta.
- Si dos preguntas equivalen, conservar:
  - mayor prioridad
  - mejor evidencia/procedencia
- Registrar `merged_from[]` para auditoría interna.

## Integración con Orchestrator

### Punto de ejecución
- Ejecutar planner tras tener:
  - `analysis` y `compliance`
  - y opcionalmente `go_no_go` disponible.

### Persistencia mínima
- `session_state.intake_plan`
- `session_state.intake_progress`
- `last_orchestrator_decision.intake_hints`

## Integración con Chatbot

### Mensaje proactivo (no intrusivo)
- Trigger cuando `intake_plan` nuevo detectado.
- Mensaje:
  - "Ya tengo tu diagnóstico. Detecté X bloqueantes y Y pendientes. ¿Quieres que empecemos?"
- Si usuario acepta:
  - iniciar pregunta `current_question_id`.
- Si usuario pospone:
  - mantener plan persistido sin perder orden.

## Compatibilidad y rollout

### Fase A (Shadow)
- Planner genera plan pero no altera `pending_questions`.

### Fase B (Dual)
- Publicar plan + mantener legacy.
- Chat usa plan como primario.

### Fase C (Primary)
- Intake plan sustituye flujo legacy para preguntas de perfil/licitación.

## Riesgos y mitigaciones

- **Riesgo:** duplicar lógica con GoNoGo/DataGap.
  - **Mitigación:** IntakePlanner solo orquesta y prioriza; no reevalúa semáforo.

- **Riesgo:** proactividad molesta al usuario.
  - **Mitigación:** saludo con opt-in explícito.

- **Riesgo:** inconsistencias entre panel y chat.
  - **Mitigación:** `provenance_ui` común y `priority` canónica compartida.

## Métricas de éxito

- Menor número de bloqueos tardíos en generación.
- Reducción de iteraciones chat “a ciegas”.
- Mayor tasa de planes de intake completados antes de generar.
