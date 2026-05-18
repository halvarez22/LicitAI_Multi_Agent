# Writer Agent Design

## Arquitectura de Componentes

El `WriterAgent` está diseñado bajo el patrón "Tool-Assisted Generation" y funciona como un puente de síntesis entre el motor de indexación (VectorDB) y el estado de memoria (MCPContextManager).

### Diagrama de Interacción
1. **Petición Entrante:** El Frontend invoca el endpoint de "Magic Draft" con el `requirement_id`.
2. **Context Manager (MCP):**
   - Extrae `company_profile` del `Repository`.
   - Extrae la Sesión Actual del `Repository`.
3. **Retrieval-Augmented Generation (RAG):**
   - Utiliza `VectorDbServiceClient.query_texts()` filtrando de forma aislada por el `session_id`.
   - Busca instrucciones específicas de "formato" en los PDFs indexados.
4. **ResilientLLMClient:**
   - Inyecta un System Prompt robusto con el patrón `ANTI_PLACEHOLDER_PROMPT_RULE`.
   - Formatea el User Prompt dividiéndolo en: *Requerimiento, Perfil y Fragmentos de Bases*.

### Manejo de Errores y Aislamiento (Lecciones Aprendidas)
- **Aislamiento Semántico:** El RAG DEBE ejecutarse usando `query_texts()` síncrono, garantizando que el `session_id` actúe como Namespace Hardcoded para evitar la fuga de datos (cross-pollination) entre diferentes licitaciones.
- **Tolerancia a Nulos:** Si el contexto RAG falla o devuelve vacío, el agente sigue adelante redactando con un formato estándar generalizado, sin quebrar el pipeline.
