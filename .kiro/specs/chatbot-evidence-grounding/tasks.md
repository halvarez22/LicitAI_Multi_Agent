# Plan de Implementación: Grounding de Evidencia

## Fase 1: Mejora de la Extracción
- [ ] Modificar `_document_candidates_prompt_section` en `chatbot_rag.py` para extraer `evidencia_en_bases` (o `snippet`) y `pagina`.
- [ ] Implementar un formateador que limpie el snippet (quitar saltos de línea excesivos) para ahorrar tokens.

## Fase 2: Blindaje del Prompt
- [ ] Actualizar el bloque de instrucciones para obligar al asistente a usar la evidencia inyectada.
- [ ] Añadir una cláusula anti-alucinación: "No inventes formatos ni requisitos de firmas si el snippet ya describe la condición".

## Fase 3: Pruebas de Estrés
- [ ] Validar con la pregunta: "¿Qué dice la bases sobre Garantía de seriedad?".
- [ ] Verificar que la respuesta cite textualmente: "que el importe no sea menor al solicitado...".
- [ ] Verificar que mencione la página correcta.
