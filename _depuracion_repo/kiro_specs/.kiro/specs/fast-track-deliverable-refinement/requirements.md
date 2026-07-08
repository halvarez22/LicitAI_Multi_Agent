# Especificaciones: Refinamiento de Lista de Candidatos (Deliverable Focus)

## 1. Objetivo
Asegurar que la lista de "Documentos Detectados" sea una herramienta útil y limpia para el usuario, enfocándose exclusivamente en los **entregables** (documentos a generar o presentar) y eliminando el ruido de requisitos puramente informativos.

## 2. Requerimientos Funcionales
- **RF-1: Foco en Entregables**: La lista de candidatos solo debe incluir ítems cuya acción propuesta sea `generar` o `presentar_fisico`.
- **RF-2: Exclusión de Ruido Informativo**: Cualquier hallazgo clasificado como `informativo` por el LLM o el Router Legal debe ser filtrado del listado final.
- **RF-3: Persistencia Robusta**: El listado de candidatos debe estar disponible en el UI (Dictamen) incluso si el pipeline se detiene por pausas económicas o falta de datos, evitando estados vacíos.

## 3. Criterios de Aceptación
- Al pulsar el botón "Documentos Detectados", el usuario no debe ver artículos de ley, glosarios o textos informativos.
- El conteo de documentos debe ser coherente con los entregables reales de la licitación (ej. ~20-80 documentos en lugar de +200).
- La lista debe persistir tras recargar la sesión sin necesidad de re-analizar.
