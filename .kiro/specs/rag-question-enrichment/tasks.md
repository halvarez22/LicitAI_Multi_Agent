# Plan de Implementación: rag-question-enrichment

## Overview

Reemplazar la implementación interna de `_enrich_pending_with_rag_context` en `ChatbotRAGAgent` y agregar tres métodos auxiliares estáticos privados. El único archivo de producción modificado es `backend/app/agents/chatbot_rag.py`. Los tests se crean en `backend/tests/agents/test_rag_question_enrichment.py`.

## Tasks

- [ ] 1. Agregar constantes de clase a `ChatbotRAGAgent`
  - En `backend/app/agents/chatbot_rag.py`, agregar las siguientes constantes como atributos de clase de `ChatbotRAGAgent` (antes de `__init__` o junto a otras constantes de clase existentes):
    - `RAG_RELEVANCE_THRESHOLD: float = 0.75`
    - `RAG_CONTEXT_MAX_CHARS: int = 400`
    - `RAG_CONTEXT_MIN_CHARS: int = 30`
    - `RAG_ENRICHABLE_PREFIXES: tuple` con los cinco prefijos estructurados
    - `_DOMAIN_TERMS_MAP: dict` con los diez pares subcadena → términos de dominio definidos en el diseño
  - Eliminar la variable local `RAG_ENRICHABLE_PREFIXES` que actualmente existe dentro del cuerpo de `_enrich_pending_with_rag_context` (será reemplazada por la constante de clase)
  - _Requirements: 2.1, 2.2, 3.1, 4.1, 4.5, 4.6_

- [ ] 2. Implementar `_build_rag_query`
  - [ ] 2.1 Agregar el método estático `_build_rag_query(pending_question: Dict[str, Any]) -> str` a `ChatbotRAGAgent`
    - Si `type == "intake_planner"`: construir query como `question + " " + reason` (omitir reason si está vacío)
    - Si no: obtener label con `_humanize_field_target(field_target)` y buscar el primer match en `_DOMAIN_TERMS_MAP` por subcadena del `field_target`; concatenar label + términos encontrados
    - Si la query resultante tiene menos de 10 caracteres: usar `_humanize_field_target(field_target)` como fallback
    - Retornar `query.strip()`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 2.2 Escribir property test para `_build_rag_query` (Property 4)
    - **Property 4: `_build_rag_query` incluye el `question` original para `intake_planner`**
    - **Validates: Requirements 1.1, 1.2**
    - Usar `@settings(max_examples=200)` con `st.text(min_size=10)` para `question`
    - Verificar que `question in query` para todo `pending_question` con `type == "intake_planner"` y `question` no vacío

- [ ] 3. Implementar `_truncate_to_sentence`
  - [ ] 3.1 Agregar el método estático `_truncate_to_sentence(text: str, max_chars: int, min_chars: int) -> str` a `ChatbotRAGAgent`
    - Si `len(text) <= max_chars` y el texto ya termina en `.`, `!`, `?`, `,` o `;`: retornar tal cual
    - Truncar a `max_chars`; buscar hacia atrás el último `.`, `!` o `?`; cortar ahí (incluir el separador)
    - Fallback: buscar hacia atrás la última `,` o `;`; cortar ahí
    - Fallback final: usar el texto truncado a `max_chars` tal cual
    - Si `len(resultado) < min_chars`: retornar `""` (señal de descarte)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [ ]* 3.2 Escribir property test para `_truncate_to_sentence` — longitud máxima (Property 1)
    - **Property 1: `_truncate_to_sentence` nunca retorna más de `max_chars` caracteres**
    - **Validates: Requirements 4.1, 4.6**
    - Usar `st.text(min_size=0, max_size=2000)`, `st.integers(min_value=10, max_value=1000)` para `max_chars`, `st.integers(min_value=1, max_value=50)` para `min_chars`
    - `assume(min_chars < max_chars)`; verificar `len(result) <= max_chars`

  - [ ]* 3.3 Escribir property test para `_truncate_to_sentence` — terminación en separador (Property 2)
    - **Property 2: cuando el texto contiene un separador dentro de los primeros `max_chars`, el resultado termina en separador**
    - **Validates: Requirements 4.2, 4.3, 4.4**
    - Construir texto como `prefix + sep + suffix` donde `sep ∈ {'.', '!', '?', ',', ';'}` y `prefix` no contiene separadores
    - Verificar que `result[-1] in SEPARATORS` o `result == text[:400]` cuando `result` no es vacío

- [ ] 4. Implementar `_is_rag_context_clean`
  - [ ] 4.1 Agregar el método estático `_is_rag_context_clean(text: str, min_chars: int) -> bool` a `ChatbotRAGAgent`
    - Retornar `False` si `len(text) < min_chars`
    - Retornar `False` si `re.search(r'\w+\.\w+', text)` encuentra match
    - Retornar `True` en caso contrario
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 4.2 Escribir property test para `_is_rag_context_clean` — rechazo de namespaces (Property 3)
    - **Property 3: `_is_rag_context_clean` retorna `False` para cualquier texto que contenga el patrón `\w+\.\w+`**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - Generar `word_a` y `word_b` con `st.from_regex(r'[a-zA-Z_]{2,10}', fullmatch=True)` y `surrounding` con `st.text(min_size=30, max_size=200)`
    - Construir `text = surrounding + word_a + '.' + word_b + surrounding`; verificar `result is False`

- [ ] 5. Reemplazar `_enrich_pending_with_rag_context`
  - [ ] 5.1 Reemplazar el cuerpo completo del método `_enrich_pending_with_rag_context` en `backend/app/agents/chatbot_rag.py` siguiendo el pseudocódigo PASCAL del diseño
    - Mantener la firma exacta: `async def _enrich_pending_with_rag_context(self, session_id: str, pending_question: Dict[str, Any]) -> Dict[str, Any]`
    - Validar `session_id` vacío o `None` → retornar original sin búsqueda
    - Determinar `is_intake` y `is_structured` usando `RAG_ENRICHABLE_PREFIXES`; si ninguno → retornar original
    - Llamar a `_build_rag_query(pending_question)` para obtener la query
    - Llamar a `self.vector_db.query_texts(session_id, query, n_results=3)` dentro de `try/except`; en excepción → `logger.warning("rag_enrichment_failed", ...)` y retornar original
    - Validar que `distances` y `documents` no estén vacíos → retornar original si lo están
    - Validar `score = distances[0] <= RAG_RELEVANCE_THRESHOLD`; si no → `logger.debug("rag_score_too_high", ...)` y retornar original
    - Llamar a `_truncate_to_sentence(documents[0], RAG_CONTEXT_MAX_CHARS, RAG_CONTEXT_MIN_CHARS)`; si retorna `""` → retornar original
    - Llamar a `_is_rag_context_clean(rag_context, RAG_CONTEXT_MIN_CHARS)`; si `False` → `logger.warning("rag_technical_variable_detected", ...)` y retornar original
    - Crear `enriched = dict(pending_question)`, asignar `enriched["rag_context"] = rag_context`
    - Registrar `logger.info("rag_enrichment_success", session_id=..., field_target=..., query_type=..., rag_chars=..., score=...)`
    - Retornar `enriched`
    - _Requirements: 1.1–1.6, 2.1–2.5, 3.1–3.5, 4.1–4.6, 5.1–5.4, 6.1–6.6, 7.1–7.5, 8.1–8.7_

  - [ ]* 5.2 Escribir property test — inmutabilidad ante fallos (Property 5)
    - **Property 5: ante cualquier fallo, `_enrich_pending_with_rag_context` retorna el mismo objeto `pending_question` recibido (identidad `result is pending_question`)**
    - **Validates: Requirements 6.1, 6.6, 8.2**
    - Usar mock de `vector_db` que lanza `Exception`; generar `pending_question` con `st.fixed_dictionaries`
    - Verificar `result is pending_question` (identidad de objeto, no solo igualdad)

  - [ ]* 5.3 Escribir property test — score alto implica retorno del original (Property 6)
    - **Property 6: para cualquier score > `RAG_RELEVANCE_THRESHOLD`, el método retorna el original sin campo `rag_context`**
    - **Validates: Requirements 3.3**
    - Usar `st.floats(min_value=RAG_RELEVANCE_THRESHOLD + 0.001, max_value=2.0, allow_nan=False)` para el score
    - Verificar `result is pending_question` y `"rag_context" not in result`

- [ ] 6. Checkpoint — verificar integración de métodos auxiliares
  - Asegurarse de que todos los tests de propiedades pasan. Preguntar al usuario si hay dudas antes de continuar.

- [ ] 7. Escribir tests de ejemplo (pytest)
  - [ ] 7.1 Crear `backend/tests/agents/test_rag_question_enrichment.py` con fixture `make_agent` que construye un `ChatbotRAGAgent` con mocks de `llm` y `vector_db`
    - _Requirements: 8.1_

  - [ ]* 7.2 Test: enriquecimiento exitoso end-to-end
    - Mock de `query_texts` con `documents=["Las bases exigen capital contable mínimo de $2,000,000 MXN (Cláusula 8.3)."]` y `distances=[0.3]`
    - Verificar que `result["rag_context"]` existe, `len(result["rag_context"]) <= 400` y `result is not pending_question`
    - _Requirements: 3.2, 4.1, 4.6, 8.2_

  - [ ]* 7.3 Test: `_build_rag_query` incluye términos de dominio para campo estructurado
    - Verificar que para `field_target="solvencia_economica.capital_contable"` la query contiene "capital contable"
    - _Requirements: 1.3, 1.4_

  - [ ]* 7.4 Test: logging de enriquecimiento exitoso
    - Verificar que `logger.info` se llama con `session_id`, `field_target`, `rag_chars` y `score`
    - _Requirements: 7.1_

  - [ ]* 7.5 Test: logging de score alto
    - Mock con `distances=[0.9]`; verificar que `logger.debug` se llama con el score
    - _Requirements: 3.3, 7.2_

  - [ ]* 7.6 Test: logging de variable técnica detectada
    - Mock con fragmento que contiene `"solvencia_legal.rfc"`; verificar que `logger.warning` se llama con los primeros 80 chars del fragmento
    - _Requirements: 5.1, 5.2, 7.3_

  - [ ]* 7.7 Test: `session_id` vacío retorna original sin llamar a `query_texts`
    - Verificar que `vector_db.query_texts` no se llama y `result is pending_question`
    - _Requirements: 6.4_

  - [ ]* 7.8 Test: tipos no enriquecibles retornan el original
    - Probar `type="quality_validation_blocking"`, `type="economic_price"`, `type="economic_validation_blocking"` con `field_target` sin prefijo estructurado
    - Verificar `result is pending_question` en los tres casos
    - _Requirements: 2.3, 2.4, 2.5_

  - [ ]* 7.9 Test: respuesta de ChromaDB con listas vacías retorna original sin excepciones
    - Mock con `{"documents": [], "distances": []}` y con `{"documents": [], "distances": None}`
    - Verificar `result is pending_question` sin que se lance ninguna excepción
    - _Requirements: 3.5, 6.2_

  - [ ]* 7.10 Test: fragmento con namespace técnico es descartado
    - Mock con `documents=["El campo solvencia_legal.rfc debe presentarse notariado."]` y `distances=[0.2]`
    - Verificar `result is pending_question` y `"rag_context" not in result`
    - _Requirements: 5.1, 5.2_

- [ ] 8. Checkpoint final — todos los tests pasan
  - Ejecutar `pytest backend/tests/agents/test_rag_question_enrichment.py -v` y verificar que todos los tests pasan. Preguntar al usuario si hay dudas antes de cerrar.

## Notes

- Las sub-tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido.
- Cada tarea referencia requisitos específicos para trazabilidad completa.
- Los checkpoints garantizan validación incremental antes de continuar.
- Los tests de propiedad (Hypothesis) validan invariantes universales; los tests de ejemplo validan comportamientos concretos y logging.
- El único archivo de producción modificado es `backend/app/agents/chatbot_rag.py`.
