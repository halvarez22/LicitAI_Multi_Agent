# Especificaciones: Grounding de Evidencia en el Asistente (Chatbot Evidence Grounding)

## 1. Objetivo
Dotar al asistente conversacional de la capacidad de citar evidencia textual directa y números de página validados por el motor de auditoría, eliminando alucinaciones y búsquedas fallidas.

## 2. Requerimientos Funcionales
- **RF-1: Inyección de Snippets**: El asistente debe recibir el fragmento de texto (`snippet` o `evidencia_en_bases`) asociado a cada documento detectado.
- **RF-2: Precisión de Ubicación**: El asistente debe incluir el número de página validado por el detector para cada requisito.
- **RF-3: Veracidad de Contenido**: El asistente debe priorizar el texto extraído por el detector sobre su conocimiento general para explicar requisitos administrativos.

## 3. Criterios de Aceptación
- Al preguntar "¿Qué dice la bases sobre [Documento]?", el asistente debe responder citando la evidencia exacta detectada.
- Al preguntar "¿En qué página está [Documento]?", el asistente debe responder con el número de página que el detector guardó en los metadatos.
- Se debe evitar la alucinación de requisitos generales si existe evidencia específica en las bases.
