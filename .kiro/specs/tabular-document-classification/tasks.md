# Plan de Implementación: tabular-document-classification

## Visión General

Tres cambios quirúrgicos para evitar que el sistema genere contenido ficticio en documentos tabulares:
1. Agregar `requiere_datos_licitante` al prompt del `ComplianceAgent`
2. Tratar `requiere_datos_licitante` como `presentar_fisico` en `FormatsAgent` y `TechnicalWriterAgent`
3. Agregar mensaje UX empático en el `ChatbotRAGAgent`

## Tareas

- [x] 1. Agregar `requiere_datos_licitante` al prompt del `ComplianceAgent`
  - Archivo: `backend/app/agents/compliance.py`
  - En la sección `CLASIFICACIÓN tipo_accion`, agregar la definición del nuevo tipo:
    ```
    - "requiere_datos_licitante": documento tabular/cuantitativo que requiere datos del licitante
      (cantidades, precios, plazos, programas de obra). El sistema NO puede generarlo automáticamente
      porque los números son privados del licitante.
    ```
  - Agregar ejemplos de clasificación para documentos tabulares:
    - "AT-13 Programa calendarizado de materiales" → `requiere_datos_licitante`
    - "Programa calendarizado de suministro de materiales y equipo" → `requiere_datos_licitante`
    - "Catálogo de conceptos con cantidades y precios" → `requiere_datos_licitante`
    - "Explosivo de insumos" → `requiere_datos_licitante`
    - "Análisis de precios unitarios" → `requiere_datos_licitante`
    - "Programa de ejecución de obra" → `requiere_datos_licitante`
    - "Programa de utilización de maquinaria y equipo" → `requiere_datos_licitante`
    - "Tabulador de salarios" → `requiere_datos_licitante`
  - _Requisitos: 1.1, 1.2, 1.5_

- [x] 2. Actualizar `FormatsAgent` para omitir documentos `requiere_datos_licitante`
  - Archivo: `backend/app/agents/formats.py`
  - Localizar la condición que filtra `informativo` y `presentar_fisico`
  - Agregar `requiere_datos_licitante` al conjunto de tipos omitidos:
    ```python
    if tipo_accion in ("informativo", "presentar_fisico", "requiere_datos_licitante"):
        continue
    ```
  - _Requisitos: 1.3, 2.1_

- [ ] 3. Actualizar `TechnicalWriterAgent` para omitir documentos `requiere_datos_licitante`
  - Archivo: `backend/app/agents/technical_writer.py`
  - Localizar la función `_should_generate_document` o equivalente
  - Agregar `requiere_datos_licitante` al conjunto de tipos que retornan `False`:
    ```python
    if tipo_accion in ("informativo", "presentar_fisico", "requiere_datos_licitante"):
        return False
    ```
  - _Requisitos: 1.3, 2.2_

- [ ] 4. Agregar mensaje UX empático en el `ChatbotRAGAgent`
  - Archivo: `backend/app/agents/chatbot_rag.py`
  - Agregar constante `_REQUIERE_DATOS_MSG` con el mensaje de Gemini
  - En `_build_session_resume_message`, detectar documentos `requiere_datos_licitante` en el inventario y mostrar el mensaje
  - El mensaje debe incluir el nombre específico del documento detectado
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 5. Escribir tests unitarios
  - Archivo: `backend/tests/test_tabular_document_classification.py`
  - `test_compliance_classifica_programa_calendarizado`: verifica que "AT-13 Programa calendarizado" → `requiere_datos_licitante`
  - `test_formats_omite_requiere_datos_licitante`: verifica que `FormatsAgent` no genera documentos con ese tipo
  - `test_technical_writer_omite_requiere_datos_licitante`: verifica que `TechnicalWriterAgent` no genera documentos con ese tipo
  - `test_documentos_generar_no_afectados`: verifica que cartas y manifiestos siguen generándose
  - _Requisitos: 1.1, 1.3, 2.1, 2.2, 4.1_

- [ ] 6. Checkpoint final — Verificar que todos los tests pasan
  - Ejecutar `pytest backend/tests/test_tabular_document_classification.py -v`
  - Ejecutar `pytest backend/tests/test_formats_agent_behavior.py backend/tests/test_technical_writer_behavior.py -v` para verificar no-regresión
  - Asegurarse de que todos los tests pasan

## Notas

- El cambio en el prompt del `ComplianceAgent` es el más impactante — afecta cómo el LLM clasifica documentos en todas las licitaciones futuras
- Las sesiones existentes con documentos ya clasificados no se ven afectadas (compatibilidad hacia atrás)
- El mensaje UX de Gemini es el tono correcto: empático, sin tecnicismos, da opciones claras
- La Fase 2 (DataExtractionAgent universal) queda en el roadmap para un sprint posterior
