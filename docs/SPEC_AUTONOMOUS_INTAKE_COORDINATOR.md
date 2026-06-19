# SPEC_AUTONOMOUS_INTAKE_COORDINATOR

## §1 Visión y Límites HITL
**Objetivo:** Construir un "Intake Autónomo Conversacional" (Nivel A) y un "Agente Generador Completo" (Nivel B). El agente recibe las bases/anexos y él solo conduce la entrevista al usuario hasta tener todo lo necesario, y posteriormente genera el expediente sin intervención manual adicional.

**Límites HITL:** 
El Nivel C (Agente Hands-Off Total) no es deseable legalmente. En licitaciones públicas, alguien tiene que firmar y responder ante el convocante. El principio `ENTERPRISE_CANONICO_HITL` se mantiene como garantía de calidad:
- El agente **no inventa** datos (RFC, precios, fechas de experiencia).
- El humano interviene estrictamente para: proveer datos faltantes (HITL), decisión de Go/No-Go, y firma del expediente.
- El salto de autonomía no viene de saltarse las validaciones, sino de orquestar las preguntas pendientes de manera ordenada y proactiva.

## §2 Métricas de Éxito
- **Fricción:** Eliminar el 70% de la fricción actual donde el usuario debe revisar manualmente el documento para saber "¿qué me falta?".
- **Criterio de Aceptación HRU (Golden Test):** 
  - Ningún gap nuevo duplica `pending_questions`. 
  - Ninguna clasificación contradice `triage_context`. 
  - Tests BARDA + Oracle siguen 100% verdes.

## §3 Schema `state_data`
Para mantener un enfoque ágil y evitar migraciones complejas en la Fase 1, la persistencia del coordinador se guardará directamente en el JSON de estado de la sesión:
- **Ubicación:** `state_data.autonomous_intake` (versionado a v1.0.0).
- **Activación:** Se controlará mediante la bandera `AUTONOMOUS_INTAKE_ENABLED` (por defecto apagada durante el desarrollo).
- **Restricción:** No se implementará un "gate" binario duro (`if not intake_complete: raise`) en el orquestador principal, para no romper flujos como `close_obra_delivery_gaps`, `repack` o `analysis_only`.

## §4 Mapa de Módulos Existentes
El principio arquitectónico es **Coordinar, no duplicar**. No se crearán agentes nuevos que compitan con la verdad canónica existente.

| Propuesta Funcional (Dominio) | Equivalente Real a Utilizar (El Coordinador delega aquí) |
|-------------------------------|----------------------------------------------------------|
| **TenderClassifier**          | `triage_context` / `TenderRouterService` |
| **GapAnalysisEngine**         | Salida consolidada de `IntakePlannerAgent`, `DataGapAgent`, `SlotInferenceService`, `economic_capture_matrix_service`, `obra_delivery_gap_service`. |
| **ConversationOrchestrator**  | `AutonomousIntakeCoordinator` (Coordinador delgado) actuando sobre `hitl_queue_service` y `ChatbotRAGAgent`. |
| **ProfileUpdater**            | Lógica existente para actualizar el `master_profile` / catálogo desde el chat. |
| **ChecklistFinalAgent**       | Pantalla/resumen final determinista (manifiesto + quality gate + checklist) reusando el delivery/Go-No-Go existente. |

## §5 Plan MVP (4 Semanas)
**Semana 1:** 
- Creación de `AutonomousIntakeCoordinator` + schema en `state_data` + flag `AUTONOMOUS_INTAKE_ENABLED`.
- Hook post-análisis.
- Pruebas de no-duplicación en `pending_questions`.

**Semana 2:** 
- Refactor mínimo de `IntakePlanner`: entrada unificada consolidando compliance + perfil + slots.
- Golden test BARDA: demostrar que solicita los mismos `[Consignar]` que actualmente se detectan, sin inventar nuevos ni omitir los de matriz económica u obra.

**Semana 3:** 
- UI/UX: Chat + `App.jsx`.
- Implementación del `IntakeProgressCard` y status API.
- Auto-resume (auto-disparo) de `generation_only` cuando la cola bloqueante esté vacía, sin tocar las reglas duras de `hitl_queue_service`.

**Semana 4:** 
- Resumen final determinista pre-firma.
- Flujo de aprobación (Go/No-Go) reutilizando el pipeline de delivery existente.

## §6 Fuera de Alcance (Fase 1)
- **TenderClassifier:** No se implementará un nuevo clasificador independiente; se confiará 100% en `triage_context`.
- **Alembic:** No se crearán tablas SQL exclusivas para este coordinador.
- **Chat Paralelo:** El chat se mantendrá enfocado en resolver la cola de gaps secuencialmente, sin abarcar intenciones desconectadas del intake en la misma vista de onboarding.
