# Diseño: Quiet Idle Chat Intake Gate

## Alcance
Implementar una compuerta de activación para mensajes de intake en backend/chatbot y render de estado en frontend, evitando ruido en sesiones inactivas.

## Componentes
- `backend/app/agents/chatbot_rag.py`
- `frontend/src/App.jsx`
- (opcional) utilitario de sesión para señales de actividad real

## Arquitectura propuesta

### 1) Señal canónica de actividad real
Definir un predicado único `has_real_work_context(session_state, company_id)` que evalúe:
- presencia de fuentes procesadas o tareas de análisis completadas,
- hints de quality gate/go-no-go/economic gap,
- pendientes reales persistidos por agentes.

Si no se cumple, el chatbot entra en **modo idle neutral**.

### 2) Gate en ChatbotRAG
Antes de promover `pending_questions` o emitir copy proactivo:
- validar `has_real_work_context`.
- si es falso:
  - no promover quality/intake pending,
  - no ejecutar bootstrap proactivo de brechas,
  - responder con mensaje neutral y factual.

### 3) Gate en Frontend (IntakeProgressCard)
Renderizar `IntakeProgressCard` solo cuando:
- `progress_total > 0` **y**
- el backend confirme contexto activo (`intake_active=true` o equivalente).

Evitar hidratar snapshot de intake en bootstrap vacío.

### 4) Mensajería factual
Reemplazar copy ambiguo por versiones condicionadas:
- Sin contexto real: "Selecciona empresa y carga fuentes para iniciar el análisis."
- Con contexto real: copy actual de guidance/intake.

## Contrato sugerido (aditivo)
En respuestas del chatbot:
```json
{
  "intake_active": false,
  "activity_state": "idle_no_sources",
  "progress_total": 0
}
```

## Riesgos y mitigación
- Riesgo: ocultar pendientes verdaderos por gate excesivo.
  - Mitigación: `has_real_work_context` incluye señales de quality/go-no-go/pending persistidos.
- Riesgo: cambios en copy afecten tests.
  - Mitigación: adaptar asserts a intención semántica y no cadenas rígidas.
