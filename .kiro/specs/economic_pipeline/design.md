# Economic Pipeline Design

## Arquitectura Basada en Estado (State-Driven Architecture)

El problema histórico de "amnesia" ocurre porque el historial conversacional (`chat_history`) es fluido y temporal. Para resolverlo, el pipeline económico se rediseña alrededor del **Estado del Contexto (MCP State)**.

### Flujo de Datos

1. **Ingesta de Datos (Frontend -> ChatbotRAGAgent):**
   - El usuario envía un mensaje: *"Precio zona 1: $100"*.
   - El `ChatbotRAGAgent`, equipado con un **Tool/Function**, detecta la intención.
   - En lugar de solo responder, el Agente invoca internamente `commit_economic_data(zona="1", precio=100)`.
   - El sistema actualiza de manera persistente `session.state_data.economic_parameters`.

2. **Validación (Orchestrator -> EconomicAgent):**
   - El orquestador nota un cambio en el estado y despierta al `EconomicAgent`.
   - `EconomicAgent` lee `economic_parameters`. Si está vacío, se detiene.
   - Si tiene datos, cruza los números contra un RAG específico para reglas financieras de la licitación (ej. Salarios mínimos en bases de limpieza).
   - Genera un dictamen y transiciona el estado de sesión a `ECONOMIC_VALIDATED` o `PENDING_ECONOMIC_INFO`.

3. **Renderizado (EconomicWriterAgent):**
   - Escucha la transición a `ECONOMIC_VALIDATED`.
   - Extrae los parámetros exactos (ej. `$100`).
   - Aplica impuestos estandarizados (IVA 16%, a menos que haya zona fronteriza detectada en bases).
   - Estructura el Anexo Económico en formato tabular (`Markdown`).

### Patrones de Resiliencia
- **Single Source of Truth:** Los precios nunca se deducen del historial de chat al generar la propuesta; siempre se extraen de `state_data.economic_parameters`.
- **Validación Estricta:** El `EconomicAgent` utiliza un prompt con formato JSON obligatorio que responde estructuradamente si hay inconsistencias matemáticas, facilitando el parseo en Python para alertar al usuario.
