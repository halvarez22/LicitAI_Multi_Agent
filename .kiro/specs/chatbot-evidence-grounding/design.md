# Diseño Técnico: Grounding de Evidencia (Evidence-Driven RAG)

## 1. Enriquecimiento del Contexto

Se modificará la lógica de inyección de candidatos para incluir datos de auditoría:

### Estructura de Datos en el Prompt:
Para cada documento, se inyectará:
```text
- [Nombre]: [Acción] | [Página]
  Evidencia: "[Snippet de texto extraído del PDF]"
```

## 2. Estrategia de Mitigación de Tokens
Como la lista puede ser larga (83 ítems), se aplicará una jerarquía:
1.  **Prioridad 1 (Accionables)**: Documentos para "Generar" o "Presentar" incluirán nombre, página y un resumen corto del snippet.
2.  **Prioridad 2 (Informativos)**: Se incluirán solo si tienen una "evidencia fuerte" detectada.
3.  **Capado**: Limitar a los primeros 60-80 ítems más relevantes para no saturar el contexto del LLM.

## 3. Refinamiento del Prompt de Respuesta
Se añadirá una regla de "Ancla de Realidad":
*"Si el usuario pregunta por el contenido o requisitos de un documento que aparece en la sección de 'HECHOS CONFIRMADOS', tu respuesta DEBE basarse exclusivamente en la 'Evidencia' proporcionada para ese ítem. No complementes con conocimientos generales de licitaciones a menos que sea explícitamente solicitado."*
