# Plan de Implementación: Generación de Documentos de Licitación

## Overview

Corrección de los gaps identificados en el orquestador y DeliveryAgent, más la suite de tests de las 10 propiedades de corrección. Los agentes ya existen y funcionan; las tareas se enfocan exclusivamente en los cambios necesarios para cerrar los gaps del diseño.

## Tasks

- [x] 1. Validación de datos de compliance en modo generation_only
  - [x] 1.1 Agregar validación explícita en `OrchestratorAgent.process()` que, cuando `mode == "generation_only"`, verifique que `tasks_completed` contiene al menos una entrada con `stage_completed == "compliance"` antes de ejecutar cualquier agente de generación
    - Si no hay datos de compliance, retornar inmediatamente con `status="error"` y `stop_reason="MISSING_PRIOR_ANALYSIS"` sin invocar ningún agente
    - Ubicación: `backend/app/agents/orchestrator.py`, al inicio del bloque de `generation_only`
    - _Requirements: 1.3, 1.5_

  - [ ]* 1.2 Escribir test unitario para la validación de compliance faltante
    - Caso: sesión sin `tasks_completed` en modo `generation_only` → retorna `stop_reason="MISSING_PRIOR_ANALYSIS"`
    - Caso: sesión con `tasks_completed` válido → pipeline continúa normalmente
    - _Requirements: 1.5_

- [x] 2. Acumulación de documentos_generados en el orquestador
  - [x] 2.1 Modificar el flujo de generación en `OrchestratorAgent.process()` para acumular `documentos_generados` tras cada agente escritor
    - Después de TechnicalWriterAgent: extraer `result.data.get("documentos", [])` → `documentos_generados["tecnica"]`
    - Después de FormatsAgent: extraer `result.data.get("documentos", [])` → `documentos_generados["administrativa"]`
    - Después de EconomicWriterAgent: extraer `result.data.get("documentos", [])` → `documentos_generados["economica"]`
    - Inyectar `documentos_generados` en `company_data` antes de invocar a `DocumentPackagerAgent`
    - _Requirements: 5.1, 5.7_

  - [ ]* 2.2 Escribir test unitario para la acumulación de documentos_generados
    - Verificar que `DocumentPackagerAgent` recibe `documentos_generados` con las tres claves (`tecnica`, `administrativa`, `economica`) populadas con los outputs de los agentes anteriores
    - _Requirements: 5.1_

- [x] 3. Checkpoint — Verificar que el orquestador pasa datos correctos a DocumentPackagerAgent
  - Asegurarse de que los tests de las tareas 1 y 2 pasan. Consultar al usuario si hay dudas sobre la estructura de `tasks_completed`.

- [ ] 4. Pasar documentos reales al DeliveryAgent
  - [x] 4.1 Modificar el flujo del orquestador para inyectar `documentos_generados` en `company_data` antes de invocar a `DeliveryAgent`
    - El `DeliveryAgent` debe recibir la lista consolidada de todos los documentos generados para construir el checklist con archivos reales
    - Ubicación: `backend/app/agents/orchestrator.py`, bloque de invocación de `DeliveryAgent`
    - _Requirements: 7.1_

  - [ ] 4.2 Modificar `DeliveryAgent` para usar `documentos_generados` del `company_data` al construir el checklist
    - Si `company_data` contiene `documentos_generados`, iterar sobre las tres categorías y agregar cada documento al checklist con estado `"Pendiente"`
    - Si `documentos_generados` no está presente, mantener el comportamiento actual (fallback)
    - Ubicación: `backend/app/agents/delivery.py`
    - _Requirements: 7.1_

  - [ ]* 4.3 Escribir test unitario para el checklist con documentos reales
    - Caso: `company_data` con `documentos_generados` populado → checklist contiene exactamente los documentos de las tres categorías
    - Caso: `company_data` sin `documentos_generados` → checklist usa fallback sin error
    - _Requirements: 7.1_

- [ ] 5. Property tests — Campos obligatorios y exactitud de WAITING_FOR_DATA (Properties 1 y 10)
  - [ ]* 5.1 Escribir property test para Property 1: campos obligatorios faltantes bloquean la generación
    - Usar `hypothesis` con `st.frozensets(st.sampled_from(["razon_social", "rfc", "representante_legal"]), min_size=1)`
    - Verificar que `FormatsAgent` y `TechnicalWriterAgent` retornan `AgentStatus.WAITING_FOR_DATA`
    - **Property 1: Campos obligatorios faltantes siempre bloquean la generación**
    - **Validates: Requirements 1.4, 3.7, 9.4**

  - [ ]* 5.2 Escribir property test para Property 10: exactitud del conjunto de campos en WAITING_FOR_DATA
    - Verificar que `data["missing"]` contiene exactamente los campos faltantes (ni más ni menos)
    - **Property 10: Campos faltantes en WAITING_FOR_DATA son exactos**
    - **Validates: Requirements 9.1, 1.4**

- [ ] 6. Property tests — Reanudación y cardinalidad de documentos (Properties 2 y 3)
  - [ ]* 6.1 Escribir property test para Property 2: reanudación no re-ejecuta stages completados
    - Mockear `ComplianceAgent` y verificar que NO es invocado cuando `tasks_completed` contiene `stage_completed == "compliance"`
    - **Property 2: Reanudación no re-ejecuta stages completados**
    - **Validates: Requirements 1.5**

  - [ ]* 6.2 Escribir property test para Property 3: cardinalidad de documentos técnicos
    - Usar `st.integers(min_value=0, max_value=20)` para N requisitos técnicos
    - Verificar que `TechnicalWriterAgent` genera exactamente N + 1 archivos DOCX
    - **Property 3: Cardinalidad de documentos técnicos**
    - **Validates: Requirements 2.1, 2.2**

- [ ] 7. Property tests — Deduplicación e invariante fiscal (Properties 4 y 5)
  - [ ]* 7.1 Escribir property test para Property 4: deduplicación de requisitos administrativos
    - Generar lista con duplicados por ID y verificar que `FormatsAgent` genera exactamente un archivo por ID único
    - **Property 4: Deduplicación de requisitos administrativos**
    - **Validates: Requirements 3.8**

  - [ ]* 7.2 Escribir property test para Property 5: invariante fiscal del cálculo económico
    - Usar `st.lists(st.fixed_dictionaries({...}), min_size=1, max_size=20)` con cantidades y precios positivos
    - Verificar `iva == round(subtotal * 0.16, 2)` y `total == round(subtotal + iva, 2)`
    - **Property 5: Invariante fiscal del cálculo económico**
    - **Validates: Requirements 4.4**

- [ ] 8. Property tests — Validación CompraNet (Properties 6, 7 y 8)
  - [ ]* 8.1 Escribir property test para Property 6: validación de extensiones de archivo
    - Generar extensiones aleatorias y verificar que solo las permitidas producen `PackResult(success=True)`
    - **Property 6: Validación de extensiones de archivo**
    - **Validates: Requirements 6.1, 6.2**

  - [ ]* 8.2 Escribir property test para Property 7: nomenclatura canónica de archivos CompraNet
    - Generar combinaciones de RFC, licitacion_id y orden y verificar el patrón `{rfc}_{lic}_{label}_{orden:02d}{ext}`
    - **Property 7: Nomenclatura canónica de archivos CompraNet**
    - **Validates: Requirements 6.3**

  - [ ]* 8.3 Escribir property test para Property 8: integridad del manifiesto SHA-256
    - Generar contenido binario aleatorio, empaquetar y verificar que el hash en el manifiesto coincide con el hash real del archivo en disco
    - **Property 8: Integridad del manifiesto SHA-256**
    - **Validates: Requirements 6.4**

- [ ] 9. Property tests — Carátulas de sobre (Property 9)
  - [ ]* 9.1 Escribir property test para Property 9: contenido de carátulas de sobre
    - Generar `master_profile` válido con datos aleatorios y lista de documentos
    - Verificar que la carátula DOCX contiene razón social, RFC, representante legal, session_id y nombres de todos los documentos del sobre
    - **Property 9: Contenido de carátulas de sobre**
    - **Validates: Requirements 5.4**

- [ ] 10. Checkpoint final — Todos los tests pasan
  - Ejecutar `pytest backend/tests/test_document_generation.py -v` y verificar que todos los tests unitarios y de propiedades pasan. Consultar al usuario si algún test falla por cambios en la interfaz de los agentes.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los property tests usan `hypothesis` con mínimo 100 iteraciones (`@settings(max_examples=100)`)
- Los tests deben ubicarse en `backend/tests/test_document_generation.py` (o subdirectorio equivalente)
- Los gaps del orquestador (tareas 1, 2, 4) son los únicos cambios de código de producción requeridos; el resto son tests
