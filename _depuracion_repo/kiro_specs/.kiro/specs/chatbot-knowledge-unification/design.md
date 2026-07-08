# Diseño Técnico: Inyección de Candidatos en el Motor RAG

## 1. Arquitectura de Contexto

Se implementará un nuevo componente de "Conciencia Documental" en el `ChatbotRAGAgent`:

### Método: `_document_candidates_prompt_section`
Este método extraerá los candidatos de la sesión y generará un bloque de texto estructurado para el LLM:
- **Entrada**: `session_state` (dict).
- **Salida**: String formateado con la lista de documentos, su categoría y acción (Generar/Presentar).

## 2. Modificaciones al Prompt de Sistema

El `system_prompt` de `_handle_rag_query` se reestructurará para incluir:
1.  **Bloque de Hechos**: La lista de candidatos detectados.
2.  **Regla de Precedencia**: Instrucción explícita de que esta lista es la "Verdad Absoluta" sobre la existencia de documentos.
3.  **Ajuste de Asertividad**: Refinar la cláusula de "no lo veo" para que solo se dispare si el documento no está ni en la lista de candidatos ni en los fragmentos RAG.

## 3. Flujo de Datos
1.  `_handle_rag_query` carga la sesión.
2.  Se llama a `_document_candidates_prompt_section`.
3.  Se concatena el resultado al `system_prompt`.
4.  El LLM genera la respuesta con conocimiento unificado.
