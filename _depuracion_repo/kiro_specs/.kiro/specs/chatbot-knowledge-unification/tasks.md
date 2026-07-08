# Plan de Implementación: Chatbot Knowledge Unification

## Fase 1: Extracción de Datos
- [ ] Implementar `_document_candidates_prompt_section` en `chatbot_rag.py`.
- [ ] Asegurar que se tomen los candidatos de `fastTrackDocumentCandidates` o `document_candidates_v1`.

## Fase 2: Integración del Prompt
- [ ] Actualizar `_handle_rag_query` para invocar el nuevo método.
- [ ] Modificar el `system_prompt` para incluir el bloque de entregables oficiales.
- [ ] Refinar las instrucciones de asertividad siguiendo las recomendaciones de Gemini.

## Fase 3: Validación
- [ ] Probar con la pregunta sobre el "Anexo III" en la sesión de UNAQ.
- [ ] Verificar que la respuesta sea inmediata, asertiva y mencione su existencia basada en el índice oficial.
- [ ] Confirmar que no hay regresiones en las respuestas informativas normales.
