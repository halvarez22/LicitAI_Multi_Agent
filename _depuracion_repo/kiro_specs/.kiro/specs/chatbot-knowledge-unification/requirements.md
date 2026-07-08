# Especificaciones: Unificación de Conocimiento del Asistente (Chatbot Knowledge Unification)

## 1. Objetivo
Eliminar las contradicciones y alucinaciones de "falta de información" en el Chatbot, dotándolo de conciencia sobre los documentos que el sistema ya ha detectado y clasificado.

## 2. Requerimientos Funcionales
- **RF-1: Inyección de Candidatos**: El Chatbot debe recibir en su prompt de sistema la lista oficial de documentos detectados (`fastTrackDocumentCandidates`) de la sesión actual.
- **RF-2: Prioridad de Hechos**: El Chatbot debe priorizar la lista de candidatos sobre la búsqueda semántica (RAG) para confirmar la **existencia** de un documento.
- **RF-3: Respuestas Asertivas**: Eliminar el comportamiento de "duda por omisión" cuando el documento está presente en el índice de entregables.
- **RF-4: Contextualización de Acción**: El asistente debe ser capaz de indicar si un documento es para "Generar" o "Presentar Físico" basándose en la clasificación del pipeline.

## 3. Criterios de Aceptación
- Si el usuario pregunta por un documento que está en la lista de 83 entregables de UNAQ, el asistente debe confirmar su existencia sin dudar.
- El asistente no debe decir "no lo veo aquí" si el documento está en la lista oficial de candidatos.
- La respuesta debe integrar el estado del entregable (Categoría y Acción propuesta).
