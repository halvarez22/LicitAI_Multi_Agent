# Session Isolation Per Tender Bugfix Design

## Overview

El sistema LicitAI presenta un bug crítico de aislamiento de datos: cuando múltiples licitaciones se procesan concurrentemente o secuencialmente, los datos de una licitación pueden mezclarse con otra. Este bug compromete la integridad fundamental del sistema, ya que el AnalystAgent puede retornar requisitos de una licitación diferente a la activa, y ChromaDB puede retornar documentos de cualquier sesión sin filtrado adecuado.

La estrategia de corrección se basa en tres pilares:
1. **Aislamiento en ChromaDB**: Garantizar que cada consulta filtre estrictamente por session_id
2. **Validación en MCPContextManager**: Verificar que todas las operaciones de contexto pertenezcan a la sesión activa
3. **Detección automática de licitación**: Identificar la licitación por número/nombre en el documento y validar contra session_id

## Glossary

- **Bug_Condition (C)**: La condición que dispara el bug - cuando una operación de datos (consulta ChromaDB, extracción de requisitos, persistencia) opera sin validación de session_id o con session_id incorrecto
- **Property (P)**: El comportamiento deseado - todas las operaciones de datos deben estar aisladas por session_id, garantizando que los datos de una licitación nunca se mezclen con otra
- **Preservation**: El comportamiento existente que debe mantenerse - procesamiento correcto de documentos, extracción de requisitos, y flujo de trabajo entre agentes para una sola licitación
- **session_id**: Identificador único de sesión que representa una licitación específica. Debe ser único, inmutable y validado en cada operación
- **ChromaDB**: Base de datos vectorial que almacena embeddings de documentos. Actualmente usa session_id como nombre de colección pero tiene fallback cross-collection que puede mezclar datos
- **MCPContextManager**: Gestor de contexto que coordina el flujo entre agentes. No valida que los datos pertenezcan a la sesión correcta
- **AnalystAgent**: Agente que extrae requisitos de licitaciones. Usa smart_search que consulta ChromaDB sin validación de sesión
- **VectorDbServiceClient**: Cliente de ChromaDB que implementa el método `_pick_vector_collection` con fallback cross-collection problemático

## Bug Details

### Bug Condition

El bug se manifiesta cuando el sistema realiza operaciones de datos sin validación estricta de session_id. Las condiciones específicas son:

1. **ChromaDB Cross-Collection Fallback**: El método `_pick_vector_collection` busca datos en otras colecciones si la colección principal está vacía, sin validar que los datos pertenezcan a la sesión correcta
2. **MCPContextManager sin Validación**: No verifica que los datos recuperados pertenezcan al session_id de la operación actual
3. **AnalystAgent sin Verificación**: Extrae requisitos sin validar que el contexto recuperado pertenezca a la licitación activa
4. **Session ID No Determinístico**: El session_id se pasa como parámetro pero no se valida contra el contenido del documento

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type DataOperation
  OUTPUT: boolean
  
  // Caso 1: ChromaDB cross-collection fallback
  IF input.operation_type == "vector_query" THEN
    collection := get_collection(input.session_id)
    IF collection.is_empty() AND exists_other_collection_with_session_id(input.session_id) THEN
      RETURN TRUE  // Fallback puede mezclar datos
    END IF
  END IF
  
  // Caso 2: MCPContextManager sin validación
  IF input.operation_type == "context_retrieval" THEN
    context := get_global_context(input.session_id)
    IF NOT validate_session_ownership(context, input.session_id) THEN
      RETURN TRUE  // Contexto puede contener datos de otra sesión
    END IF
  END IF
  
  // Caso 3: AnalystAgent sin verificación
  IF input.operation_type == "requirement_extraction" THEN
    search_results := smart_search(input.session_id, input.query)
    FOR EACH result IN search_results DO
      IF result.metadata.session_id != input.session_id THEN
        RETURN TRUE  // Resultados de otra sesión
      END IF
    END FOR
  END IF
  
  // Caso 4: Session ID no validado contra documento
  IF input.operation_type == "document_upload" THEN
    detected_tender := detect_tender_from_document(input.document_content)
    IF detected_tender != None AND detected_tender != input.session_id THEN
      RETURN TRUE  // Documento pertenece a otra licitación
    END IF
  END IF
  
  RETURN FALSE
END FUNCTION
```

### Examples

1. **Ejemplo 1: Cross-Collection Fallback**
   - Sesión activa: "paneles-solares-2024"
   - Colección "paneles-solares-2024" está vacía
   - Sistema busca en otras colecciones y encuentra datos de "issste-bcs-2024"
   - Resultado: AnalystAgent retorna requisitos de ISSSTE en lugar de PANELES SOLARES

2. **Ejemplo 2: Contexto Mezclado**
   - Usuario trabaja en licitación "LIC-001-2024"
   - Cambia a licitación "LIC-002-2024"
   - MCPContextManager no limpia contexto previo
   - Resultado: get_global_context retorna datos mezclados de ambas licitaciones

3. **Ejemplo 3: Documento de Otra Licitación**
   - Usuario sube documento con título "BASES LIC-003-2024"
   - session_id pasado: "lic-001-2024"
   - Sistema no detecta la discrepancia
   - Resultado: Documento de LIC-003 se asocia a sesión de LIC-001

4. **Caso Edge: Sesión con Mismo Nombre Sanitizado**
   - session_id: "ISSSTE-BCS-2024" y "issste_bcs_2024"
   - Sanitización produce mismo nombre de colección
   - Resultado: Datos de ambas sesiones se mezclan en una colección

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- El procesamiento de documentos (OCR, extracción, indexación) debe continuar funcionando correctamente para una sola licitación
- La extracción de requisitos por AnalystAgent debe mantener la calidad y precisión actuales
- El flujo de trabajo entre IngestionAgent, AnalystAgent, ComplianceAgent y EconomicAgent debe permanecer intacto
- La funcionalidad de vector search y recuperación semántica debe mantenerse
- La persistencia en PostgreSQL debe continuar siendo robusta
- La interfaz de usuario y los endpoints API no deben cambiar su contrato

**Scope:**
Todas las operaciones que involucren una sola licitación deben funcionar exactamente como antes. El aislamiento es transparente para el usuario final cuando trabaja en una única licitación.

## Hypothesized Root Cause

Basado en el análisis del código, las causas raíz identificadas son:

1. **Cross-Collection Fallback en VectorDbServiceClient**
   - El método `_pick_vector_collection` (líneas 36-75) implementa un fallback que busca en TODAS las colecciones si la colección principal está vacía
   - Este mecanismo fue diseñado para resiliencia pero viola el aislamiento de sesiones
   - El flag `need_session_where` se usa para filtrar, pero solo funciona si los metadatos contienen session_id correcto

2. **Falta de Validación en MCPContextManager**
   - `get_global_context` recupera datos sin verificar ownership
   - `record_task_completion` no valida que el resultado pertenezca a la sesión
   - No existe un mecanismo de "session lock" para operaciones atómicas

3. **AnalystAgent Confía en session_id Sin Validación**
   - El método `process` recibe session_id como parámetro y lo pasa a `smart_search`
   - No verifica que los resultados retornados pertenezcan a la sesión
   - La búsqueda semántica puede retornar documentos de otras sesiones si el fallback está activo

4. **Session ID No Derivado del Contenido**
   - El session_id se pasa externamente y no se valida contra el contenido del documento
   - No existe detección automática de número/nombre de licitación en el documento
   - Un usuario puede subir documento de "LIC-001" a sesión "LIC-002" sin que el sistema lo detecte

5. **Sanitización de Nombres de Colección**
   - El método `_sanitize_name` puede producir colisiones (ej: "ISSSTE-BCS-2024" y "issste_bcs_2024" → mismo nombre)
   - No hay validación de unicidad de session_id sanitizado

## Correctness Properties

Property 1: Bug Condition - ChromaDB Session Isolation

_For any_ vector database query operation where the bug condition holds (isBugCondition returns true due to cross-collection fallback or missing session_id filter), the fixed VectorDbServiceClient SHALL enforce strict session_id filtering at the metadata level, ensuring that no documents from a different session_id are returned, even when the primary collection is empty.

**Validates: Requirements 2.3**

Property 2: Bug Condition - MCPContextManager Session Validation

_For any_ context retrieval operation where the bug condition holds (isBugCondition returns true due to missing session ownership validation), the fixed MCPContextManager SHALL validate that all data in the retrieved context belongs exclusively to the specified session_id, rejecting or filtering any data that does not match.

**Validates: Requirements 2.5**

Property 3: Bug Condition - AnalystAgent Data Verification

_For any_ requirement extraction operation where the bug condition holds (isBugCondition returns true due to unverified search results), the fixed AnalystAgent SHALL verify that all search results and extracted data belong to the active session_id before including them in the analysis output.

**Validates: Requirements 2.2**

Property 4: Bug Condition - Automatic Tender Detection

_For any_ document upload operation where the bug condition holds (isBugCondition returns true due to session_id mismatch with document content), the fixed upload process SHALL detect the tender identifier from the document content and either warn the user or reject the document if it does not match the active session_id.

**Validates: Requirements 2.1**

Property 5: Preservation - Single Session Processing

_For any_ input where the bug condition does NOT hold (single session processing without cross-session operations), the fixed system SHALL produce exactly the same results as the original system, preserving all document processing, requirement extraction, and agent workflow functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

**File**: `backend/app/services/vector_service.py`

**Function**: `VectorDbServiceClient`

**Specific Changes**:

1. **Eliminar Cross-Collection Fallback Problemático**:
   - Modificar `_pick_vector_collection` para NO buscar en otras colecciones
   - Si la colección principal está vacía, retornar vacío (no buscar en otras)
   - Mantener el flag `need_session_where` para colecciones compartidas (caso legado)

2. **Agregar Validación de session_id en Metadatos**:
   - En `add_texts`, verificar que todos los metadatos contengan session_id
   - En `query_texts`, SIEMPRE filtrar por session_id en el where clause
   - En `query_texts_filtered`, agregar session_id al where clause siempre

3. **Método de Validación de Sesión**:
   - Agregar `validate_session_ownership(session_id, metadata)` que verifica que metadata.session_id == session_id
   - Usar en todos los métodos de consulta

**File**: `backend/app/agents/mcp_context.py`

**Function**: `MCPContextManager`

**Specific Changes**:

1. **Validación de Ownership en get_global_context**:
   - Agregar parámetro `expected_session_id` y validar que todos los datos pertenezcan a esa sesión
   - Filtrar documentos que no pertenezcan a la sesión

2. **Validación en record_task_completion**:
   - Verificar que el resultado no contenga referencias a otras sesiones
   - Agregar método `_validate_task_result_ownership(session_id, result)`

3. **Session Lock Mechanism**:
   - Agregar métodos `acquire_session_lock(session_id)` y `release_session_lock(session_id)`
   - Usar para operaciones atómicas que involucren múltiples agentes

**File**: `backend/app/agents/analyst.py`

**Function**: `AnalystAgent.process`

**Specific Changes**:

1. **Verificación de Resultados de Búsqueda**:
   - Después de cada `smart_search`, verificar que los metadatos contengan el session_id correcto
   - Agregar método `_verify_search_results_session(results, expected_session_id)`

2. **Logging de Sesión**:
   - Agregar logging explícito de session_id en cada operación
   - Incluir session_id en mensajes de error para debugging

**File**: `backend/app/api/v1/routes/upload.py`

**Function**: `upload_file`, `process_document`

**Specific Changes**:

1. **Detección Automática de Licitación**:
   - Agregar función `detect_tender_from_document(file_path, filename)` que extrae número/nombre de licitación
   - Patrones regex para formatos comunes: "LIC-XXX-YYYY", "ISSSTE-XXX-YYYY", etc.

2. **Validación de session_id vs Documento**:
   - Comparar session_id pasado con el detectado en el documento
   - Si hay discrepancia, registrar warning y/o solicitar confirmación

3. **Metadata Enriquecida**:
   - Agregar `detected_tender_id` y `session_id_validated` a los metadatos del documento

**File**: `backend/app/memory/adapters/postgres_adapter.py`

**Function**: `PostgresMemoryAdapter`

**Specific Changes**:

1. **Validación de Unicidad de session_id**:
   - En `save_session`, verificar que el session_id no colisione con otros después de sanitización
   - Agregar constraint único en la base de datos

2. **Índice por session_id**:
   - Agregar índice en tabla documents por session_id para consultas rápidas
   - Verificar que todas las consultas filtren por session_id

### Architecture of Session Isolation

```
┌─────────────────────────────────────────────────────────────────┐
│                     SESSION ISOLATION LAYER                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │   Upload Route   │───▶│ Tender Detector  │                   │
│  │                  │    │  (regex/LLM)     │                   │
│  └────────┬─────────┘    └────────┬─────────┘                   │
│           │                       │                              │
│           ▼                       ▼                              │
│  ┌──────────────────────────────────────────┐                   │
│  │        Session Validation Gate           │                   │
│  │  - Validate session_id vs detected tender│                   │
│  │  - Reject or warn on mismatch            │                   │
│  │  - Add validated metadata                │                   │
│  └────────────────────┬─────────────────────┘                   │
│                       │                                          │
│           ┌───────────┴───────────┐                             │
│           ▼                       ▼                             │
│  ┌─────────────────┐    ┌─────────────────┐                     │
│  │   PostgreSQL    │    │    ChromaDB     │                     │
│  │  (Session State)│    │  (Vectors RAG)  │                     │
│  │                 │    │                 │                     │
│  │ - session_id PK │    │ - Collection    │                     │
│  │ - FK validation │    │   per session   │                     │
│  │ - Unique index  │    │ - Metadata      │                     │
│  │                 │    │   session_id    │                     │
│  └────────┬────────┘    └────────┬────────┘                     │
│           │                       │                              │
│           └───────────┬───────────┘                             │
│                       ▼                                          │
│  ┌──────────────────────────────────────────┐                   │
│  │         MCPContextManager                │                   │
│  │  - Validate ownership on retrieval       │                   │
│  │  - Session lock for atomic operations    │                   │
│  │  - Filter cross-session data             │                   │
│  └────────────────────┬─────────────────────┘                   │
│                       │                                          │
│           ┌───────────┴───────────┐                             │
│           ▼                       ▼                             │
│  ┌─────────────────┐    ┌─────────────────┐                     │
│  │  AnalystAgent   │    │ Other Agents    │                     │
│  │                 │    │                 │                     │
│  │ - Verify search │    │ - Validate      │                     │
│  │   results       │    │   session_id    │                     │
│  │ - Log session   │    │ - Log session   │                     │
│  └─────────────────┘    └─────────────────┘                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Integrity Validations Between Agents

```
┌─────────────────────────────────────────────────────────────────┐
│              AGENT INTEGRITY VALIDATION FLOW                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. IngestionAgent                                               │
│     └─▶ Validate: document.session_id == active_session_id       │
│     └─▶ Output: {session_id, doc_id, validated: true}           │
│                                                                  │
│  2. AnalystAgent                                                 │
│     └─▶ Input: Verify session_id from previous agent            │
│     └─▶ Process: Filter all ChromaDB queries by session_id      │
│     └─▶ Output: {session_id, analysis, validated: true}         │
│                                                                  │
│  3. ComplianceAgent                                              │
│     └─▶ Input: Verify session_id matches analysis.session_id    │
│     └─▶ Process: Use only data from correct session             │
│     └─▶ Output: {session_id, compliance, validated: true}       │
│                                                                  │
│  4. EconomicAgent                                                │
│     └─▶ Input: Verify session_id from context                   │
│     └─▶ Process: Filter line_items by session_id                │
│     └─▶ Output: {session_id, proposal, validated: true}         │
│                                                                  │
│  VALIDATION CHECKPOINT:                                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ IF any_agent.output.session_id != active_session_id THEN   │ │
│  │   RAISE SessionIsolationError                              │ │
│  │   LOG security_event with details                          │ │
│  │   HALT pipeline                                            │ │
│  │ END IF                                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Testing Strategy

### Validation Approach

La estrategia de testing sigue un enfoque de tres fases:
1. **Exploratory Bug Condition Checking**: Demostrar el bug en código no corregido
2. **Fix Checking**: Verificar que la corrección funciona para todos los casos del bug
3. **Preservation Checking**: Verificar que el comportamiento existente se mantiene

### Exploratory Bug Condition Checking

**Goal**: Demostrar el bug antes de implementar la corrección. Confirmar la hipótesis de causa raíz.

**Test Plan**: Crear tests que simulen las condiciones del bug y observen fallos en el código actual.

**Test Cases**:
1. **Cross-Collection Fallback Test**: Crear dos sesiones, vaciar la colección de una, verificar que el sistema NO retorna datos de la otra sesión (fallará en código actual)
2. **Session Mismatch Test**: Subir documento con contenido de "LIC-001" a sesión "LIC-002", verificar que el sistema NO detecta la discrepancia (fallará en código actual)
3. **Context Pollution Test**: Crear contexto para sesión A, cambiar a sesión B, verificar que get_global_context retorna datos mezclados (fallará en código actual)
4. **AnalystAgent Cross-Session Test**: Indexar documentos en sesión A, ejecutar AnalystAgent en sesión B vacía, verificar que retorna requisitos de sesión A (fallará en código actual)

**Expected Counterexamples**:
- VectorDbServiceClient._pick_vector_collection retorna datos de otra sesión
- MCPContextManager.get_global_context retorna documentos de otra sesión
- AnalystAgent.process retorna requisitos de otra licitación
- Upload no detecta discrepancia entre session_id y contenido del documento

### Fix Checking

**Goal**: Verificar que para todos los inputs donde la condición del bug se cumple, el código corregido produce el comportamiento esperado.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := fixedSystem(input)
  ASSERT result.session_id == input.expected_session_id
  ASSERT NOT contains_data_from_other_sessions(result)
END FOR
```

**Test Cases**:
1. **ChromaDB Isolation Test**: Con múltiples sesiones en ChromaDB, verificar que cada consulta retorna SOLO datos de la sesión especificada
2. **MCPContextManager Validation Test**: Verificar que get_global_context filtra datos de otras sesiones
3. **AnalystAgent Verification Test**: Verificar que AnalystAgent rechaza o filtra resultados de otras sesiones
4. **Tender Detection Test**: Verificar que la detección automática identifica correctamente la licitación y valida contra session_id

### Preservation Checking

**Goal**: Verificar que para todos los inputs donde la condición del bug NO se cumple, el código corregido produce el mismo resultado que el código original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT originalSystem(input) = fixedSystem(input)
END FOR
```

**Testing Approach**: Property-based testing para generar muchos casos de uso normal y verificar que el comportamiento no cambia.

**Test Cases**:
1. **Single Session Processing**: Procesar una licitación completa y verificar que todos los resultados son idénticos al sistema original
2. **Document Upload Flow**: Verificar que el flujo de upload y procesamiento funciona igual
3. **Agent Workflow**: Verificar que el flujo entre agentes funciona igual
4. **Vector Search Quality**: Verificar que la calidad de búsqueda semántica se mantiene

### Unit Tests

- Test de `VectorDbServiceClient.query_texts` con filtrado estricto de session_id
- Test de `MCPContextManager.get_global_context` con validación de ownership
- Test de `AnalystAgent._verify_search_results_session`
- Test de `detect_tender_from_document` con varios formatos de licitación
- Test de sanitización de session_id sin colisiones

### Property-Based Tests

- Generar sesiones aleatorias con documentos y verificar aislamiento
- Generar operaciones concurrentes en múltiples sesiones y verificar no contaminación cruzada
- Generar documentos con varios formatos de identificación de licitación y verificar detección correcta
- Verificar que para cualquier operación, session_id en metadatos siempre coincide con el esperado

### Integration Tests

- Test de flujo completo: upload → process → analyze → compliance → economic con aislamiento
- Test de múltiples sesiones concurrentes con datos diferentes
- Test de cambio de sesión y verificación de limpieza de contexto
- Test de detección de licitación con documentos reales (PDFs de licitaciones mexicanas)
