# Diseño Técnico: Arquitectura del Router y Peritaje Legal

## 1. Componentes
- **`TenderRouterService`**: Lógica de Triage y Taxonomía.
- **`AgentInput`**: Propagación del `triage_context`.
- **`Orchestrator`**: Control del pre-flight normativo.

## 2. Flujo (Pipeline de Dos Pasos)
1. **Triage:** Gemini Flash analiza páginas 1-10 para extraer el marco legal.
2. **Auditoría:** Inyección de Must-Have Matrix en Analyst y Compliance.

## 3. Lógica de Agente
- El Agente ya no decide si algo es informativo basado en "feeling", sino que contrasta contra la matriz de la ley detectada.
- Uso de `is_mandatory: true` para forzar acciones.
