# Documento de Requisitos: rag-question-enrichment

## Introducción

El `ChatbotRAGAgent` de LicitAI tiene un método `_enrich_pending_with_rag_context` que enriquece las `pending_questions` con fragmentos reales de las bases de licitación antes de formularlas al usuario. El objetivo es que el LLM pueda citar cláusulas concretas al preguntar, por ejemplo: "Las bases exigen capital contable mínimo de $2,000,000 MXN (Cláusula 8.3) — ¿cuál es el tuyo?"

El método actual tiene cinco deficiencias concretas:

1. **Queries de búsqueda pobres**: usa solo `label + extra_terms` hardcodeados por tipo de campo, ignorando el `question` original del `IntakePlannerAgent` y el `provenance_reason`, que son semánticamente más ricos.
2. **Cobertura limitada**: solo enriquece campos con prefijos `condiciones_contractuales.`, `solvencia_economica.`, `solvencia_legal.`, `solvencia_tecnica.`, `gng_`. Los campos de tipo `intake_planner` (que tienen `question` y `provenance_ui.reason` ricos) quedan sin enriquecer.
3. **Sin validación de relevancia**: toma el primer resultado de ChromaDB sin verificar si el score de distancia supera un umbral mínimo, lo que puede traer fragmentos irrelevantes de otra sección del documento.
4. **Sin fallback inteligente**: si ChromaDB no retorna resultados, no hay estrategia alternativa para construir contexto desde los metadatos disponibles en la propia `pending_question`.
5. **Truncado incoherente**: el `rag_context` se corta en 600 chars sin garantizar que termine en oración completa, lo que puede producir citas truncadas a mitad de frase.

Esta feature reemplaza la lógica interna de `_enrich_pending_with_rag_context` y agrega métodos auxiliares privados en `ChatbotRAGAgent`, sin modificar ningún otro componente del sistema.

---

## Glosario

- **ChatbotRAGAgent**: Agente conversacional principal (`backend/app/agents/chatbot_rag.py`). Componente único modificado por esta feature.
- **pending_question**: Diccionario en la lista `pending_questions` del `session_state` que representa un dato faltante. Contiene `field_target`, `label`, `question`, `type`, `provenance_ui`, entre otros. No se modifica su estructura.
- **field_target**: Clave técnica del campo en el `master_profile` (ej: `solvencia_economica.capital_contable`). Nunca debe ser visible para el usuario.
- **rag_context**: Campo que se agrega al `pending_question` enriquecido. Contiene el fragmento real de las bases de licitación relevante para ese campo. Máximo 400 caracteres, siempre termina en oración completa.
- **query_semántica**: Texto construido por el `Enricher` para buscar en ChromaDB. Para campos `intake_planner`, usa el `question` original. Para otros tipos, usa el label humanizado más términos del dominio.
- **score_de_relevancia**: Distancia coseno retornada por ChromaDB. Un score bajo (cercano a 0) indica alta similitud. Un score alto (cercano a 1 o mayor) indica baja relevancia.
- **umbral_de_relevancia**: Valor máximo de distancia coseno aceptable para considerar un fragmento relevante. Definido como constante en el código.
- **VectorDbServiceClient**: Cliente de ChromaDB (`backend/app/services/vector_service.py`). No se modifica. Expone `query_texts(session_id, query, n_results)` que retorna `{"documents": [...], "distances": [...]}`.
- **IntakePlannerAgent**: Agente que genera `pending_questions` de tipo `intake_planner` con `question` y `provenance_ui.reason` ricos. No se modifica.
- **Enricher**: Nombre interno del componente lógico que implementa la nueva versión de `_enrich_pending_with_rag_context` y sus métodos auxiliares.
- **tipo_intake_planner**: `pending_question` cuyo campo `type` es `"intake_planner"`. Tiene `question` semánticamente rico generado por el `IntakePlannerAgent`.
- **tipo_estructurado**: `pending_question` con `field_target` que comienza con uno de los prefijos estructurados: `condiciones_contractuales.`, `solvencia_economica.`, `solvencia_legal.`, `solvencia_tecnica.`, `gng_`.

---

## Requisitos

### Requisito 1: Construcción de query semántica enriquecida

**User Story:** Como desarrollador, quiero que el `Enricher` construya queries de búsqueda semánticamente ricas para ChromaDB, para que los fragmentos recuperados sean más relevantes al campo específico que se está preguntando.

#### Criterios de Aceptación

1. WHEN el `pending_question` tiene `type == "intake_planner"`, THE `Enricher` SHALL construir la query semántica usando el campo `question` del `pending_question` como texto principal de búsqueda.
2. WHEN el `pending_question` tiene `type == "intake_planner"` y además tiene `provenance_ui.reason` no vacío, THE `Enricher` SHALL concatenar el `provenance_ui.reason` a la query semántica para enriquecerla.
3. WHEN el `pending_question` tiene `type != "intake_planner"` y su `field_target` comienza con un prefijo estructurado conocido, THE `Enricher` SHALL construir la query semántica usando el label humanizado del `field_target` como texto principal.
4. WHEN el `pending_question` tiene `type != "intake_planner"` y su `field_target` comienza con un prefijo estructurado conocido, THE `Enricher` SHALL agregar términos del dominio específicos al tipo de campo (ej: para `capital` → "capital contable mínimo requerido"; para `penalizacion` → "pena convencional multa retraso").
5. THE query semántica construida SHALL tener una longitud mínima de 10 caracteres para garantizar que la búsqueda en ChromaDB sea significativa.
6. IF la query semántica resultante tiene menos de 10 caracteres, THEN THE `Enricher` SHALL usar el label humanizado del `field_target` como query de fallback.

---

### Requisito 2: Cobertura universal de campos enriquecibles

**User Story:** Como desarrollador, quiero que el `Enricher` procese todos los campos que pueden tener contexto en las bases de licitación, incluyendo los de tipo `intake_planner`, para maximizar la calidad de las preguntas generadas por el LLM.

#### Criterios de Aceptación

1. WHEN el `pending_question` tiene `type == "intake_planner"`, THE `Enricher` SHALL intentar el enriquecimiento RAG independientemente del valor de `field_target`.
2. WHEN el `pending_question` tiene `field_target` que comienza con `condiciones_contractuales.`, `solvencia_economica.`, `solvencia_legal.`, `solvencia_tecnica.` o `gng_`, THE `Enricher` SHALL intentar el enriquecimiento RAG.
3. WHEN el `pending_question` tiene `type` distinto de `"intake_planner"` y su `field_target` no comienza con ningún prefijo estructurado conocido, THE `Enricher` SHALL retornar el `pending_question` sin cambios (sin intentar búsqueda en ChromaDB).
4. WHEN el `pending_question` tiene `type == "quality_validation_blocking"`, THE `Enricher` SHALL retornar el `pending_question` sin cambios.
5. WHEN el `pending_question` tiene `type == "economic_validation_blocking"` o `type == "economic_price"`, THE `Enricher` SHALL retornar el `pending_question` sin cambios.

---

### Requisito 3: Validación de relevancia por score de distancia

**User Story:** Como desarrollador, quiero que el `Enricher` valide el score de relevancia del fragmento recuperado de ChromaDB antes de usarlo, para evitar que el LLM cite fragmentos de secciones irrelevantes del documento.

#### Criterios de Aceptación

1. THE `Enricher` SHALL definir una constante `RAG_RELEVANCE_THRESHOLD` con el valor máximo de distancia coseno aceptable para considerar un fragmento relevante.
2. WHEN ChromaDB retorna un fragmento con distancia menor o igual a `RAG_RELEVANCE_THRESHOLD`, THE `Enricher` SHALL usar ese fragmento para construir el `rag_context`.
3. WHEN ChromaDB retorna un fragmento con distancia mayor a `RAG_RELEVANCE_THRESHOLD`, THE `Enricher` SHALL descartar ese fragmento y retornar el `pending_question` sin `rag_context`.
4. WHEN ChromaDB retorna múltiples fragmentos, THE `Enricher` SHALL evaluar el score del primer fragmento (el de mayor similitud) para decidir si es relevante.
5. WHEN ChromaDB retorna una lista de distancias vacía o con valores nulos, THE `Enricher` SHALL tratar el fragmento como no relevante y retornar el `pending_question` sin cambios.

---

### Requisito 4: Truncado coherente del rag_context

**User Story:** Como desarrollador, quiero que el `rag_context` resultante siempre sea una oración completa y no exceda 400 caracteres, para que el LLM reciba citas legibles y el prompt no se sature.

#### Criterios de Aceptación

1. THE `Enricher` SHALL truncar el fragmento recuperado a un máximo de 400 caracteres antes de asignarlo como `rag_context`.
2. WHEN el fragmento truncado a 400 caracteres no termina en puntuación de fin de oración (`.`, `!`, `?`), THE `Enricher` SHALL buscar hacia atrás el último punto, signo de exclamación o signo de interrogación dentro del texto truncado y cortar ahí.
3. WHEN el fragmento truncado no contiene ningún punto, signo de exclamación ni signo de interrogación, THE `Enricher` SHALL buscar la última coma o punto y coma para cortar en un límite de frase natural.
4. WHEN el fragmento truncado no contiene ningún separador de frase, THE `Enricher` SHALL usar el fragmento truncado tal cual, sin agregar puntuación artificial.
5. THE `rag_context` resultante SHALL tener una longitud mínima de 30 caracteres para garantizar que contiene información útil; si el fragmento válido es menor a 30 caracteres, THE `Enricher` SHALL descartar el fragmento y retornar el `pending_question` sin `rag_context`.
6. THE `rag_context` resultante SHALL tener una longitud máxima de 400 caracteres en todos los casos.

---

### Requisito 5: Ausencia de variables técnicas en el rag_context

**User Story:** Como usuario de LicitAI, quiero que el contexto de las bases que el chatbot me cita no contenga variables técnicas del sistema, para que la experiencia sea completamente natural.

#### Criterios de Aceptación

1. THE `Enricher` SHALL verificar que el `rag_context` candidato no contiene el patrón de namespace técnico `\w+\.\w+` (palabra, punto, palabra) antes de asignarlo al `pending_question`.
2. WHEN el `rag_context` candidato contiene el patrón `\w+\.\w+`, THE `Enricher` SHALL descartar ese fragmento y retornar el `pending_question` sin `rag_context`.
3. THE `rag_context` resultante SHALL NEVER contener strings que coincidan con el patrón regex `\b\w+\.\w+_\w+\b` (indicador de variable técnica con namespace y guión bajo).
4. WHEN el fragmento de ChromaDB contiene únicamente variables técnicas sin texto legible, THE `Enricher` SHALL descartar el fragmento completo.

---

### Requisito 6: Resiliencia total ante fallos externos

**User Story:** Como desarrollador, quiero que el `Enricher` nunca bloquee el flujo conversacional ante cualquier fallo externo o condición inesperada, para garantizar la estabilidad del sistema en producción.

#### Criterios de Aceptación

1. WHEN `VectorDbServiceClient.query_texts` lanza una excepción de cualquier tipo, THE `Enricher` SHALL capturar la excepción, registrar un log de advertencia, y retornar el `pending_question` original sin cambios.
2. WHEN ChromaDB retorna una respuesta con estructura inesperada (listas vacías, claves faltantes, valores nulos), THE `Enricher` SHALL retornar el `pending_question` original sin cambios sin lanzar excepciones.
3. WHEN el `pending_question` recibido no tiene los campos esperados (`field_target`, `type`, `question`), THE `Enricher` SHALL retornar el `pending_question` sin cambios sin lanzar excepciones.
4. WHEN el `session_id` recibido es vacío o None, THE `Enricher` SHALL retornar el `pending_question` sin cambios sin intentar la búsqueda en ChromaDB.
5. THE método `_enrich_pending_with_rag_context` SHALL ser asíncrono y SHALL completar su ejecución en todos los casos (con o sin enriquecimiento) sin bloquear el flujo conversacional.
6. IF el enriquecimiento falla por cualquier razón, THEN THE `Enricher` SHALL NEVER modificar el `pending_question` original — el objeto retornado en caso de fallo SHALL ser el mismo objeto recibido sin mutaciones.

---

### Requisito 7: Logging y observabilidad del enriquecimiento

**User Story:** Como desarrollador, quiero que el `Enricher` registre eventos clave del proceso de enriquecimiento, para poder diagnosticar problemas de calidad de las queries y relevancia de los fragmentos en producción.

#### Criterios de Aceptación

1. WHEN el `Enricher` enriquece exitosamente un `pending_question`, THE `Enricher` SHALL registrar un log de nivel `info` con: `session_id`, `field_target`, `query_type` (intake_planner o estructurado), longitud del `rag_context` resultante, y score de distancia del fragmento usado.
2. WHEN el `Enricher` descarta un fragmento por score de relevancia insuficiente, THE `Enricher` SHALL registrar un log de nivel `debug` con: `session_id`, `field_target`, y el score de distancia que causó el descarte.
3. WHEN el `Enricher` descarta un fragmento por contener variables técnicas, THE `Enricher` SHALL registrar un log de nivel `warning` con: `session_id`, `field_target`, y los primeros 80 caracteres del fragmento descartado.
4. WHEN `VectorDbServiceClient.query_texts` lanza una excepción, THE `Enricher` SHALL registrar un log de nivel `warning` con: `session_id`, `field_target`, y los primeros 80 caracteres del mensaje de error.
5. THE `Enricher` SHALL NEVER registrar el contenido completo de los fragmentos de ChromaDB en los logs para evitar saturar el sistema de logging con textos largos.

---

### Requisito 8: Compatibilidad con el pipeline existente

**User Story:** Como desarrollador, quiero que el `Enricher` mejorado sea un reemplazo directo del método actual sin romper ningún flujo existente, para garantizar que el despliegue sea seguro.

#### Criterios de Aceptación

1. THE método `_enrich_pending_with_rag_context` SHALL mantener la misma firma: `async def _enrich_pending_with_rag_context(self, session_id: str, pending_question: Dict[str, Any]) -> Dict[str, Any]`.
2. THE `Enricher` SHALL NEVER modificar la estructura de `pending_questions` en `session_state` — solo agrega el campo `rag_context` al diccionario retornado (copia del original).
3. THE `Enricher` SHALL NEVER modificar el flujo de persistencia en `master_profile` ni el índice `current_question_index`.
4. WHEN el `Enricher` agrega `rag_context` al `pending_question`, THE campo `rag_context` SHALL ser consumido por `_build_mission_context` con la prioridad ya establecida: `rag_context > clausula_texto > question_original`.
5. THE `Enricher` SHALL NEVER realizar llamadas adicionales al LLM — el enriquecimiento es exclusivamente búsqueda vectorial en ChromaDB.
6. THE `Enricher` SHALL NEVER modificar `VectorDbServiceClient` ni la interfaz de ChromaDB.
7. WHILE el `Enricher` está ejecutando la búsqueda en ChromaDB, THE `ChatbotRAGAgent` SHALL mantener disponible el `pending_question` original como fallback en caso de fallo.
