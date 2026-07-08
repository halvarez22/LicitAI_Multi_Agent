# Documento de Requisitos

## Introduccion

La feature **Asistente de Intake para Licitacion** cierra las brechas identificadas en el flujo de armado de propuestas de LicitAI. Hoy el sistema puede analizar bases, auditar cumplimiento y generar documentos, pero carece de un componente que, una vez analizadas las bases, genere automaticamente la lista completa y priorizada de preguntas que la empresa debe responder para participar en esa licitacion especifica.

Esta feature introduce tres capacidades nuevas que se integran sobre la infraestructura existente sin romper contratos:

1. **Extension del AnalystAgent**: Agrega tres nuevos campos estructurados al output del analisis de bases: condiciones contractuales (penalizaciones, condiciones de pago, garantia de vicios ocultos), requisitos de solvencia legal (padron de proveedores, comprobante de domicilio fiscal) y requisitos de solvencia economica (estados financieros auditados, declaracion anual ISR, capital minimo requerido).

2. **IntakePlannerAgent**: Nuevo agente que, dado el output del AnalystAgent + ComplianceAgent + GoNoGoAgent + master_profile actual de la empresa, genera la lista completa y priorizada de preguntas pendientes para esa licitacion especifica. Distingue entre preguntas de Tipo A (datos del perfil de empresa) y preguntas de Tipo B (requisitos derivados de las bases especificas).

3. **Flujo conversacional proactivo**: El ChatbotRAGAgent detecta automaticamente cuando las bases ya fueron analizadas, invoca al IntakePlannerAgent para obtener la lista priorizada de preguntas, e inicia la conversacion sin esperar que el usuario pregunte, presentando primero los knock-outs, luego los requisitos de solvencia, luego las condiciones contractuales y finalmente los datos complementarios del perfil.

El spec es autocontenido: un desarrollador que lo lea sin conocer el proyecto debe entender que construir.


## Glosario

- **AnalystAgent**: Agente existente (`backend/app/agents/analyst.py`) que lee las bases ingestadas y extrae cronograma, requisitos de participacion, requisitos de filtro/exclusion, garantias, criterios de evaluacion, reglas economicas y alcance operativo.
- **ComplianceAgent**: Agente existente que audita las bases con arquitectura Map-Reduce y produce una lista maestra de requisitos clasificados en: `administrativo`, `tecnico`, `formatos`, con `tipo_accion` (generar/presentar_fisico/informativo).
- **GoNoGoAgent**: Agente existente que compara el perfil de empresa contra los requisitos de las bases y detecta brechas. Calcula semaforo RED/YELLOW/GREEN.
- **DataGapAgent**: Agente existente (`backend/app/agents/data_gap.py`) que detecta campos faltantes en el `master_profile` de la empresa y genera `pending_questions` para datos genericos del perfil.
- **ChatbotRAGAgent**: Agente conversacional existente que opera en modos QUERY, DATA_INTAKE, META y PENDING. Puede capturar datos del usuario y guardarlos en el `master_profile`.
- **IntakePlannerAgent**: Nuevo agente definido en este spec. Dado el output del AnalystAgent + ComplianceAgent + GoNoGoAgent + master_profile actual, genera la lista completa y priorizada de preguntas pendientes para una licitacion especifica.
- **Pregunta Tipo A**: Pregunta derivada de datos genericos del perfil de empresa que deben estar en el `master_profile` (RFC, razon social, representante legal, domicilio fiscal, etc.). Ya manejadas parcialmente por el DataGapAgent.
- **Pregunta Tipo B**: Pregunta derivada de lo que exige la convocante especifica en las bases de esa licitacion (certificaciones requeridas, capital minimo, contratos similares, estados financieros, condiciones contractuales, garantias especificas). No pueden generarse sin leer las bases primero.
- **Lista Priorizada de Preguntas**: Conjunto ordenado de preguntas pendientes generado por el IntakePlannerAgent, clasificadas en cuatro niveles de criticidad: BLOQUEANTE, CRITICO, IMPORTANTE y COMPLEMENTARIO.
- **Nivel BLOQUEANTE**: Preguntas cuya respuesta negativa impide la participacion en la licitacion (knock-outs). Ejemplo: "Las bases exigen certificacion ISO 9001 — la tienes?"
- **Nivel CRITICO**: Preguntas sobre requisitos de solvencia legal, tecnica y economica que determinan si la propuesta puede ser evaluada. Ejemplo: "Las bases exigen capital contable minimo de $500,000 — cual es el tuyo?"
- **Nivel IMPORTANTE**: Preguntas sobre condiciones contractuales que el usuario debe conocer y aceptar. Ejemplo: "Las bases establecen penalizacion del 2% por dia de atraso — aceptas estas condiciones?"
- **Nivel COMPLEMENTARIO**: Preguntas sobre datos del perfil que mejoran la calidad de los documentos generados pero no bloquean la participacion. Ejemplo: "Cuantos empleados tiene la empresa?"
- **master_profile**: Campo JSON del modelo `Company` en PostgreSQL donde se persisten los datos estructurados de la empresa.
- **pending_questions**: Lista de objetos almacenada en `session_state` (Redis) que contiene las preguntas pendientes para el flujo conversacional.
- **session_state**: Estado de sesion versionado (`SessionStateV1`) gestionado por `MCPContextManager` y persistido en Redis.
- **condiciones_contractuales**: Nuevo campo del output del AnalystAgent. Contiene penalizaciones por incumplimiento, condiciones de pago (anticipos, estimaciones, finiquito) y garantia de vicios ocultos.
- **requisitos_solvencia_legal**: Nuevo campo del output del AnalystAgent. Contiene requisitos de alta en padron de proveedores y comprobante de domicilio fiscal exigidos por la convocante.
- **requisitos_solvencia_economica**: Nuevo campo del output del AnalystAgent. Contiene requisitos de estados financieros auditados, declaracion anual ISR y capital minimo requerido exigidos por la convocante.
- **Knock-out**: Causa de descalificacion que impide la participacion si no se subsana. Proviene de `causas_desechamiento` del ComplianceAgent o de `brechas` con `is_knockout: true` del GoNoGoAgent.
- **Semaforo**: Estado de cumplimiento de la empresa frente a los requisitos de la licitacion: RED (knock-outs), YELLOW (brechas sin knock-out), GREEN (sin brechas).
- **MCPContextManager**: Gestor de contexto MCP (`backend/app/agents/mcp_context.py`) que controla el flujo y persistencia de contexto entre agentes via Redis y PostgreSQL.
- **Pipeline**: Secuencia de agentes orquestada por el `OrchestratorAgent`: Intake -> AnalystAgent -> ComplianceAgent -> GoNoGoAgent -> EconomicAgent -> Agentes de Generacion.
- **tasks_completed**: Campo del `session_state` donde el `MCPContextManager` registra los resultados de cada agente completado, accesible via `record_task_completion`.

## Requisitos funcionales

### R1 — Extension estructurada del AnalystAgent
- El output del AnalystAgent debe incluir (sin romper contrato actual):
  - `condiciones_contractuales[]`
  - `requisitos_solvencia_legal[]`
  - `requisitos_solvencia_economica[]`
- Cada item debe incluir:
  - `titulo`
  - `descripcion`
  - `criticidad` (`bloqueante|critico|importante|complementario`)
  - `evidencia` (snippet/pagina si existe)
  - `confidence` (0..1)

### R2 — Nuevo IntakePlannerAgent
- Debe consolidar entradas de:
  - Analyst,
  - Compliance,
  - GoNoGo,
  - DataGap/master_profile.
- Debe producir una `lista_prorizada_preguntas` con objetos normalizados:
  - `question_id`
  - `question_type` (`A|B`)
  - `priority` (`BLOQUEANTE|CRITICO|IMPORTANTE|COMPLEMENTARIO`)
  - `question`
  - `field_target`
  - `required_evidence`
  - `blocking` (bool)
  - `provenance_ui`

### R3 — Deduplicacion y precedencia
- El planner debe aplicar deduplicacion semantica entre fuentes.
- Debe respetar precedencia de negocio:
  `usuario/HITL > documento normalizado > master_profile > inferencia LLM`.
- Si dos fuentes discrepan, conservar la de mayor precedencia y registrar `provenance_ui`.

### R4 — Priorizacion de preguntas
- Orden obligatorio en salida:
  1) Knock-outs / bloqueantes
  2) Solvencia legal/economica/tecnica critica
  3) Condiciones contractuales importantes
  4) Complementarios de perfil

### R5 — Integracion proactiva con Chatbot
- El Chatbot debe detectar cuando hay análisis completo + plan disponible.
- Debe iniciar mensaje proactivo no intrusivo:
  - "Detecte X bloqueantes y Y pendientes. Quieres resolverlos ahora?"
- Solo tras confirmacion del usuario inicia cuestionario guiado.

### R6 — Persistencia y reanudacion
- El plan de intake debe persistirse en sesión:
  - `intake_plan`
  - `intake_plan_version`
  - `intake_progress` (`answered`, `remaining`, `current_question_id`)
- Debe soportar resume idempotente tras refresh o reconexion.

### R7 — API/UI readiness
- Debe existir contrato estable para UI/chat:
  - resumen del plan,
  - cola de preguntas,
  - estado de progreso.
- Debe coexistir con `pending_questions` legacy mientras dura rollout.

### R8 — Compatibilidad con GoNoGo y DataGap
- IntakePlanner no reemplaza GoNoGo/DataGap:
  - GoNoGo conserva decision RED/YELLOW/GREEN.
  - DataGap conserva preguntas base de perfil.
- IntakePlanner solo agrega orquestacion, priorizacion y consolidacion final.

## Requisitos no funcionales

### N1 — Auditabilidad
- Cada pregunta debe exponer `provenance_ui` con fuente y razon de prioridad.

### N2 — Determinismo
- Con misma entrada consolidada, el plan generado debe ser estable.

### N3 — Latencia operativa
- Generacion del plan debe ser sub-segundo en modo heuristico y dentro de budget definido en modo LLM-assisted.

### N4 — Seguridad operacional
- Nunca marcar como bloqueante una pregunta sin evidencia/razon trazable.

## Criterios de aceptación (producto)

- El usuario recibe plan proactivo despues de analisis, sin tener que adivinar qué preguntar.
- Los bloqueantes aparecen primero y son accionables.
- El flujo puede pausarse y reanudarse sin perder contexto.
- El sistema conserva semantica visual consistente entre chat y paneles.
