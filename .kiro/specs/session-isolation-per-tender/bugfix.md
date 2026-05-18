# Bugfix Requirements Document

## Introduction

El sistema LicitAI está mezclando datos de diferentes licitaciones, violando el principio fundamental de aislamiento de datos. Cuando un usuario trabaja en una licitación, el sistema puede procesar y mostrar datos de una licitación diferente. Este bug crítico compromete la integridad de los datos y la confianza del usuario en el sistema.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN el usuario sube documentos de una licitación (ej: "PANELES SOLARES") THEN el sistema procesa y almacena datos sin validar que pertenezcan a la sesión activa

1.2 WHEN el AnalystAgent extrae requisitos THEN el sistema puede retornar requisitos de una licitación diferente (ej: "ISSSTE-BCS-2024") en lugar de la licitación actual

1.3 WHEN se consulta ChromaDB para recuperar documentos THEN el sistema retorna documentos de cualquier licitación sin filtrar por session_id

1.4 WHEN se persiste el estado de sesión en PostgreSQL THEN el sistema no garantiza que el session_id sea único por licitación

1.5 WHEN el MCPContextManager gestiona el flujo entre agentes THEN el sistema no valida que los datos pertenezcan a la misma licitación

### Expected Behavior (Correct)

2.1 WHEN el usuario sube documentos de una licitación THEN el sistema SHALL validar y asociar los documentos exclusivamente al session_id de la licitación activa

2.2 WHEN el AnalystAgent extrae requisitos THEN el sistema SHALL retornar únicamente requisitos de la licitación correspondiente al session_id actual

2.3 WHEN se consulta ChromaDB para recuperar documentos THEN el sistema SHALL filtrar resultados por session_id y retornar solo documentos de la licitación activa

2.4 WHEN se crea o persiste una sesión en PostgreSQL THEN el sistema SHALL garantizar que cada licitación tenga un session_id único e intransferible

2.5 WHEN el MCPContextManager gestiona el flujo entre agentes THEN el sistema SHALL validar que todos los datos procesados pertenezcan al mismo session_id

### Unchanged Behavior (Regression Prevention)

3.1 WHEN el usuario trabaja con una sola licitación THEN el sistema SHALL CONTINUE TO procesar documentos y extraer requisitos correctamente

3.2 WHEN el usuario cambia entre licitaciones diferentes en momentos diferentes THEN el sistema SHALL CONTINUE TO permitir el cambio de contexto sin pérdida de datos

3.3 WHEN se almacenan documentos en ChromaDB THEN el sistema SHALL CONTINUE TO mantener la funcionalidad de vector search y recuperación semántica

3.4 WHEN el sistema persiste estado en PostgreSQL THEN el sistema SHALL CONTINUE TO mantener la integridad de las sesiones existentes

3.5 WHEN los agentes procesan documentos THEN el sistema SHALL CONTINUE TO mantener el flujo de trabajo actual entre IngestionAgent, AnalystAgent y otros agentes
