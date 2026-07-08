# Plan de Implementación: semantic-file-extractor

## Visión General

Cinco componentes nuevos que convierten la subida de archivos en una extracción activa y dirigida. Los componentes 1 y 3 son Python puro (sin LLM), el componente 2 usa el LLM existente, y los componentes 4 y 5 integran todo en el `ChatbotRAGAgent`.

## Tareas

- [x] 1. Implementar `DocumentPreprocessor` (Python puro, sin LLM)
  - Crear `backend/app/services/document_preprocessor.py`
  - Definir dataclass `PreprocessResult` con campos: `relevant_text`, `total_chars_original`, `total_chars_filtered`, `reduction_ratio`, `keywords_found`
  - Implementar `_split_into_chunks(text, chunk_size=500, overlap=50) -> List[str]`
  - Implementar `_extract_keywords(dato_solicitado) -> List[str]` — limpia stopwords y extrae tokens significativos
  - Implementar `_score_chunk(chunk, keywords) -> int` — +3 por keyword, +2 si contiene dígitos, +1 por palabras de contexto de licitación
  - Implementar `extract_relevant_sections(extracted_text, dato_solicitado, max_tokens=3000) -> PreprocessResult`
    - Dividir en chunks, calcular scores, seleccionar top-6, concatenar con "---", truncar a max_tokens*4 chars
    - Si `extracted_text` vacío → retornar `PreprocessResult` con `relevant_text=""`, `reduction_ratio=0.0`
    - Nunca lanzar excepciones
  - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [x] 2. Implementar `MissionDataExtractor` (usa LLM)
  - Crear `backend/app/agents/mission_data_extractor.py`
  - Definir dataclass `ExtractionResult` con campos: `value`, `confidence`, `source_reference`, `raw_snippet`, `extraction_status`
  - Implementar `__init__(self, llm_client)` — recibe `ResilientLLMClient`
  - Implementar `extract(self, relevant_text, mission_context) -> ExtractionResult` (async)
    - Construir system prompt con `dato_solicitado` y `por_que_importa` del mission_context
    - Llamar al LLM con temperatura 0.1 (extracción determinista) y max_tokens=300
    - Parsear respuesta JSON del LLM → `ExtractionResult`
    - Si el LLM falla o la respuesta no es JSON válido → retornar `ExtractionResult` con `extraction_status="not_found"`, `confidence=0.0`
    - Clampear `confidence` al rango [0.0, 1.0]
    - Nunca lanzar excepciones
  - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 3. Implementar `NumericValidator` (Python puro, sin LLM)
  - Crear `backend/app/services/numeric_validator.py`
  - Definir dataclass `ValidationResult` con campos: `normalized_value`, `numeric_value`, `is_valid`, `validation_notes`, `adjustment_applied`
  - Definir dataclass `DistributionResult` con campos: `is_valid`, `adjusted_values`, `adjustment_applied`, `discrepancy`
  - Implementar `_parse_mexican_currency(raw_value) -> float | None` — maneja "$1,234,567.89", "1.234.567,89", "1234567"
  - Implementar `validate_and_normalize(raw_value, field_type="text") -> ValidationResult`
    - Nunca lanzar excepciones para ningún string input
    - Para `field_type="currency"`: usar `_parse_mexican_currency`
    - Para `field_type="integer"`: parsear como entero
    - Para `field_type="text"`: retornar el valor limpio sin validación numérica
  - Implementar `validate_monthly_distribution(monthly_values, total, tolerance=0.01) -> DistributionResult`
    - Verificar que `abs(sum(monthly_values) - total) <= tolerance`
    - Si hay discrepancia: ajustar el último mes para que la suma sea exacta
    - Garantizar invariante: si `adjustment_applied=True` → `abs(sum(adjusted_values) - total) <= tolerance`
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 4. Implementar `_handle_file_upload_with_mission` en `ChatbotRAGAgent`
  - En `backend/app/agents/chatbot_rag.py`, agregar el método `_handle_file_upload_with_mission`
  - El método recibe: `session_id`, `doc_id`, `session_state`, `pending_questions`, `current_idx`, `correlation_id`
  - Flujo interno:
    1. Obtener el documento por `doc_id` desde `context_manager.memory`
    2. Extraer `extracted_text` del documento
    3. Construir `mission_context` con `_build_mission_context` (ya existe de Fase 1)
    4. Preprocesar con `DocumentPreprocessor.extract_relevant_sections`
    5. Extraer con `MissionDataExtractor.extract`
    6. Si el dato es numérico: validar con `NumericValidator.validate_and_normalize`
    7. Si `extraction_status="found"`: persistir en `session_state["pending_mapping_confirmation"]` y retornar mensaje de confirmación
    8. Si `extraction_status="not_found"`: retornar mensaje informando que no se encontró el dato
    9. Si cualquier paso falla: degradar al flujo normal (pedir el dato directamente)
  - Integrar el punto de activación en `process()`: detectar cuando el mensaje del usuario contiene un `doc_id` recién subido Y hay `pending_questions` activas
  - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.2, 6.3, 6.4_

- [x] 5. Implementar `_handle_mapping_confirmation` y `_classify_confirmation_response` en `ChatbotRAGAgent`
  - En `backend/app/agents/chatbot_rag.py`, agregar los métodos:
    - `_classify_confirmation_response(user_response) -> str` (estático) — retorna "confirm" | "correct" | "reject"
    - `_handle_mapping_confirmation(user_response, session_id, company_id, session_state, correlation_id) -> AgentOutput` (async)
  - Lógica de `_classify_confirmation_response`:
    - Tokens de confirmación: "sí", "si", "correcto", "exacto", "ok", "dale", "va", "así es"
    - Tokens de rechazo: "no aplica", "no está", "no tengo", "no lo tengo"
    - Si empieza con "no" y tiene más de 5 chars → "correct"
    - Default → "confirm"
  - Lógica de `_handle_mapping_confirmation`:
    - Leer `session_state["pending_mapping_confirmation"]`
    - Si no existe → retornar al flujo normal
    - Clasificar respuesta con `_classify_confirmation_response`
    - "confirm" → guardar `proposed_value` en `master_profile` vía `_save_field_to_company`
    - "correct" → extraer el valor corregido del mensaje y guardarlo
    - "reject" → limpiar `pending_mapping_confirmation`, mantener pregunta pendiente
    - Limpiar `pending_mapping_confirmation` de `session_state` después de confirm/correct
    - Avanzar al siguiente pendiente después de confirm/correct exitoso
  - Integrar el punto de activación en `process()`: si `pending_mapping_confirmation` existe en `session_state`, invocar `_handle_mapping_confirmation` antes del flujo normal
  - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.7_

- [x] 6. Escribir tests de propiedades con Hypothesis y tests unitarios
  - Crear `backend/tests/test_semantic_file_extractor.py`
  - **Tests unitarios:**
    - `test_preprocessor_empty_text`: texto vacío → `relevant_text=""`
    - `test_preprocessor_reduction_ratio_range`: ratio en [0.0, 1.0]
    - `test_preprocessor_max_tokens_respected`: output ≤ max_tokens * 4 chars
    - `test_preprocessor_keywords_scoring`: chunks con keywords tienen mayor score
    - `test_numeric_validator_currency_mx`: "$1,234,567.89" → 1234567.89
    - `test_numeric_validator_invalid_no_exception`: strings inválidos → `is_valid=False`, sin excepción
    - `test_monthly_distribution_valid`: suma correcta → `adjustment_applied=False`
    - `test_monthly_distribution_adjustment`: suma incorrecta → ajuste aplicado, invariante cumplido
    - `test_extraction_result_not_found`: LLM retorna `not_found` → `value=None`
    - `test_confirmation_classify_confirm`: "sí" → "confirm"
    - `test_confirmation_classify_correct`: "no, es 500000" → "correct"
    - `test_confirmation_classify_reject`: "no aplica" → "reject"
  - **Tests de propiedades (Hypothesis):**
    - `# Feature: semantic-file-extractor, Propiedad 1: DocumentPreprocessor nunca excede el límite de tokens`
      - `@given(st.text(), st.text(min_size=1), st.integers(min_value=100, max_value=5000))`
      - Verificar: `len(result.relevant_text) <= max_tokens * 4`
    - `# Feature: semantic-file-extractor, Propiedad 2: NumericValidator nunca lanza excepciones`
      - `@given(st.text())`
      - Verificar: `validate_and_normalize` no lanza excepciones
    - `# Feature: semantic-file-extractor, Propiedad 3: Invariante de ajuste proporcional`
      - `@given(st.lists(st.floats(min_value=0, max_value=1000, allow_nan=False), min_size=1, max_size=12), st.floats(min_value=0, max_value=10000, allow_nan=False))`
      - Verificar: si `adjustment_applied=True` → `abs(sum(adjusted_values) - total) <= 0.01`
    - `# Feature: semantic-file-extractor, Propiedad 4: reduction_ratio siempre en [0.0, 1.0]`
      - `@given(st.text(min_size=1), st.text(min_size=1))`
      - Verificar: `0.0 <= result.reduction_ratio <= 1.0`
  - Usar `@settings(max_examples=100)` en cada test de propiedad
  - _Requisitos: 1.3, 1.4, 1.5, 1.6, 3.1, 3.5_

## Notas

- Los componentes 1 y 3 (Python puro) deben implementarse y testearse antes de los componentes 2, 4 y 5
- El `DocumentPreprocessor` no necesita el `DocumentIngestionRouter` — recibe el `extracted_text` ya extraído
- La detección del `doc_id` en el mensaje del usuario se hace leyendo `session_state` para ver si hay documentos recién subidos (estado `UPLOADED` o `ANALYZED` con timestamp reciente)
- El flujo de confirmación usa `session_state["pending_mapping_confirmation"]` como flag de estado — si existe, el siguiente mensaje del usuario se interpreta como respuesta a la confirmación
- Para la Fase 2 MVP, el `field_type` se infiere del `field_target` del pendiente activo usando un mapa simple (campos con "capital", "monto", "precio" → "currency"; campos con "numero", "cantidad" → "integer"; resto → "text")
