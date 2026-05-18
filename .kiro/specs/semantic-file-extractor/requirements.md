# Documento de Requisitos: semantic-file-extractor

## Introducción

Cuando el asistente de LicitAI hace una pregunta al usuario (por ejemplo, "¿cuál es tu capital contable?"), el usuario puede responder de dos formas: escribiendo el dato directamente en el chat, o subiendo un archivo que lo contiene. El sistema actual maneja bien el primer caso, pero en el segundo caso simplemente indexa el archivo y espera que el usuario haga clic en "Analizar Fuentes" — sin aprovechar que el asistente ya sabe exactamente qué dato está buscando.

Este feature introduce el **Extractor Semántico Dirigido por Misión**: cuando el usuario sube un archivo con una pregunta activa, el sistema extrae automáticamente el dato específico que el asistente acaba de pedir, lo valida matemáticamente si aplica, y presenta el resultado al usuario para confirmación antes de guardarlo en su perfil.

El diseño sigue el principio "Python para filtrar y validar, LLM solo para interpretar": el 90% del trabajo (reducción del archivo, validación numérica) lo hace Python puro sin costo de API. El LLM solo recibe el fragmento relevante ya limpio.

---

## Glosario

- **DocumentPreprocessor**: Servicio Python puro que filtra un texto largo para extraer solo las secciones relevantes para un dato específico, sin usar el LLM.
- **MissionDataExtractor**: Agente que usa el LLM para extraer un dato específico de un fragmento de texto ya filtrado.
- **NumericValidator**: Servicio Python puro que valida y normaliza valores numéricos, incluyendo validación de distribuciones mensuales.
- **ExtractionResult**: Resultado de la extracción con el valor encontrado, su confianza, referencia de origen y estado.
- **PreprocessResult**: Resultado del preprocesamiento con el fragmento relevante y métricas de reducción.
- **pending_mapping_confirmation**: Campo en `session_state` que persiste el valor propuesto entre el turno de extracción y el turno de confirmación del usuario.
- **mission_context**: Diccionario construido por `_build_mission_context` (Fase 1) con el dato solicitado, su impacto y el estado de la sesión.
- **dato_solicitado**: Label legible del dato que el asistente está pidiendo (ej: "Capital contable mínimo").
- **field_type**: Tipo del campo para validación numérica: "currency" | "integer" | "percentage" | "text".
- **reduction_ratio**: Proporción del texto original que fue descartada por el preprocesador (0.0 = sin reducción, 1.0 = todo descartado).

---

## Requisitos

### Requisito 1: Pre-procesamiento Python para reducción de costo y latencia

**User Story:** Como sistema, quiero filtrar el contenido de un archivo antes de enviarlo al LLM, para que el costo de la API sea mínimo y la respuesta sea rápida independientemente del tamaño del archivo.

#### Criterios de Aceptación

1. WHEN el `DocumentPreprocessor` recibe un `extracted_text` y un `dato_solicitado`, THE `DocumentPreprocessor` SHALL dividir el texto en chunks de ~500 caracteres con overlap de 50 caracteres.
2. THE `DocumentPreprocessor` SHALL calcular un score de relevancia por chunk: +3 puntos por cada keyword del `dato_solicitado` encontrada (case-insensitive), +2 puntos si el chunk contiene dígitos, +1 punto por palabras de contexto de licitación.
3. THE `DocumentPreprocessor` SHALL retornar los top-6 chunks por score, concatenados y truncados a `max_tokens * 4` caracteres.
4. THE `PreprocessResult.reduction_ratio` SHALL estar siempre en el rango [0.0, 1.0].
5. WHEN `extracted_text` está vacío, THE `DocumentPreprocessor` SHALL retornar `PreprocessResult` con `relevant_text=""` y `reduction_ratio=0.0`.
6. THE `DocumentPreprocessor` SHALL NOT lanzar excepciones para ninguna combinación válida de inputs.
7. THE `DocumentPreprocessor` SHALL NOT invocar ningún LLM ni servicio externo.

---

### Requisito 2: Extracción semántica dirigida por el dato activo

**User Story:** Como usuario, quiero que el asistente encuentre automáticamente el dato que me pidió dentro del archivo que subí, para no tener que buscarlo manualmente ni escribirlo de nuevo.

#### Criterios de Aceptación

1. WHEN el `MissionDataExtractor` recibe un `relevant_text` y un `mission_context`, THE `MissionDataExtractor` SHALL invocar al LLM con un prompt que incluya el `dato_solicitado` y el `por_que_importa` del contexto.
2. THE `ExtractionResult.confidence` SHALL estar siempre en el rango [0.0, 1.0].
3. WHEN el LLM no encuentra el dato en el texto, THE `MissionDataExtractor` SHALL retornar `ExtractionResult` con `extraction_status="not_found"` y `value=None`.
4. WHEN el LLM encuentra múltiples valores posibles igualmente válidos, THE `MissionDataExtractor` SHALL retornar `extraction_status="ambiguous"` con el valor más probable en `value`.
5. WHEN el LLM falla por error de red o timeout, THE `MissionDataExtractor` SHALL retornar `ExtractionResult` con `extraction_status="not_found"` y `confidence=0.0` sin propagar la excepción.
6. THE `ExtractionResult` SHALL incluir `source_reference` con la ubicación del dato en el archivo (ej: "Hoja 2, fila 15", "Página 3, párrafo 2").
7. THE `MissionDataExtractor` SHALL NOT lanzar excepciones para ninguna combinación válida de inputs.

---

### Requisito 3: Validación matemática Python para datos numéricos

**User Story:** Como sistema, quiero validar y normalizar los valores numéricos extraídos usando Python puro, para garantizar que los montos y distribuciones mensuales sean matemáticamente correctos antes de guardarlos.

#### Criterios de Aceptación

1. THE `NumericValidator.validate_and_normalize` SHALL NOT lanzar excepciones para ningún string input, incluyendo strings vacíos, con caracteres especiales o con formatos inválidos.
2. THE `NumericValidator` SHALL reconocer y normalizar formatos monetarios mexicanos: "$1,234,567.89", "1.234.567,89", "1234567", "1,234,567".
3. WHEN `validate_monthly_distribution` recibe una lista de valores mensuales y un total, THE `NumericValidator` SHALL verificar que `sum(monthly_values)` es igual a `total` con una tolerancia de `tolerance` (default: 0.01).
4. WHEN la suma de los valores mensuales no coincide con el total, THE `NumericValidator` SHALL aplicar un ajuste proporcional automático al último mes para que la suma sea exacta.
5. IF `DistributionResult.adjustment_applied=True`, THEN `abs(sum(adjusted_values) - total) <= tolerance` SHALL ser verdadero.
6. WHEN el `raw_value` no es parseable como número, THE `NumericValidator` SHALL retornar `ValidationResult` con `is_valid=False` y `numeric_value=None`.
7. THE `NumericValidator` SHALL NOT invocar ningún LLM ni servicio externo.

---

### Requisito 4: Presentación del mapeo para confirmación del usuario

**User Story:** Como usuario, quiero ver qué valor encontró el asistente en mi archivo y de dónde lo sacó, para poder confirmar que es correcto antes de que se guarde en mi perfil.

#### Criterios de Aceptación

1. WHEN el `MissionDataExtractor` retorna `extraction_status="found"`, THE `ChatbotRAGAgent` SHALL presentar al usuario un mensaje de confirmación que incluya el `dato_solicitado`, el `value` encontrado y el `source_reference`.
2. THE mensaje de confirmación SHALL ofrecer tres opciones explícitas: confirmar, corregir con un valor diferente, o indicar que no aplica.
3. THE `ChatbotRAGAgent` SHALL persistir el valor propuesto en `session_state["pending_mapping_confirmation"]` antes de retornar el mensaje de confirmación.
4. WHEN el `MissionDataExtractor` retorna `extraction_status="not_found"`, THE `ChatbotRAGAgent` SHALL comunicar al usuario que no encontró el dato en el archivo y mantener la pregunta pendiente activa.
5. WHEN el `MissionDataExtractor` retorna `extraction_status="ambiguous"`, THE `ChatbotRAGAgent` SHALL presentar el valor más probable y pedir confirmación explícita.
6. THE mensaje de confirmación SHALL NOT contener variables técnicas ni nombres de campos del sistema.

---

### Requisito 5: Procesamiento de la respuesta de confirmación

**User Story:** Como usuario, quiero que el asistente entienda mi respuesta de confirmación (sí/no/corrección) y actúe en consecuencia, para que el flujo sea natural y no tenga que repetir información.

#### Criterios de Aceptación

1. WHEN el usuario responde con una señal de confirmación ("sí", "si", "correcto", "exacto", "ok", "dale"), THE `ChatbotRAGAgent` SHALL guardar el `proposed_value` en el `master_profile` de la empresa.
2. WHEN el usuario responde con una corrección ("no, es X", "no, el valor es X", "en realidad es X"), THE `ChatbotRAGAgent` SHALL extraer el valor X de la respuesta y guardarlo en el `master_profile`.
3. WHEN el usuario responde con un rechazo ("no aplica", "no está", "no tengo"), THE `ChatbotRAGAgent` SHALL limpiar `pending_mapping_confirmation` de `session_state` y mantener la pregunta pendiente activa.
4. AFTER guardar el dato exitosamente, THE `ChatbotRAGAgent` SHALL limpiar `pending_mapping_confirmation` de `session_state` y avanzar al siguiente pendiente.
5. THE `_classify_confirmation_response` SHALL retornar uno de: "confirm" | "correct" | "reject".
6. IF `pending_mapping_confirmation` no existe en `session_state`, THE `ChatbotRAGAgent` SHALL ignorar el mensaje de confirmación y continuar con el flujo normal de pendientes.

---

### Requisito 6: Integración con el flujo existente sin romper nada

**User Story:** Como desarrollador, quiero que el extractor semántico sea una extensión del flujo existente que no rompa ningún comportamiento actual, para garantizar la estabilidad del sistema en producción.

#### Criterios de Aceptación

1. THE extractor semántico SHALL activarse ONLY cuando hay una `pending_question` activa Y el usuario sube un archivo en el mismo turno conversacional.
2. WHEN no hay `pending_questions` activas, THE sistema SHALL procesar el archivo con el flujo existente (indexación pasiva en ChromaDB).
3. THE `DocumentPreprocessor` SHALL usar el `extracted_text` del `DocumentIngestionRouter` existente, sin modificar el router.
4. IF cualquier componente del extractor falla, THE `ChatbotRAGAgent` SHALL degradar al comportamiento anterior: pedir el dato directamente al usuario en el chat.
5. THE extractor semántico SHALL NOT modificar el flujo de `economic_price` ni `economic_validation_blocking` — esos flujos tienen su propio manejo.
6. THE extractor semántico SHALL NOT requerir cambios en el frontend.
7. THE `session_state["pending_mapping_confirmation"]` SHALL ser limpiado después de cada confirmación exitosa o rechazo, para no interferir con turnos posteriores.
