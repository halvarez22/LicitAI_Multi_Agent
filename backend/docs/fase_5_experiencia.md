# Fase 5: Memoria de Experiencia y Casos Similares (MVP)

Esta fase implementa un mecanismo de recuperación de experiencia previa para guiar el análisis de nuevas licitaciones en LicitAI. No es un sistema de aprendizaje estadístico pesado, sino una capa de **RAG Basado en Casos (Case-Based RAG)**.

## Arquitectura de Experiencia

### 1. Fuente de Verdad: PostgreSQL
Se utiliza la tabla `licitacion_outcomes` para registrar el veredicto final de cada proceso.
- **Campos Clave**: `session_id`, `sector`, `tipo_licitacion`, `resultado` (GANADA, PERDIDA, etc.), y `requirements_fingerprint`.
- **Huella Digital (Fingerprint)**: Un hash normalizado de los requisitos detectados que permite identificar si el perfil de la licitación actual ya se ha visto antes exactamente igual.

### 2. Índice Semántico: ChromaDB
Se utiliza la colección `experience_cases` en ChromaDB para realizar búsquedas por similitud.
- **Justificación**: Usamos ChromaDB en lugar de PGVector para mantener coherencia con el stack actual de la aplicación (RAG de documentos). Permite búsquedas semánticas rápidas sin depender de extensiones complejas de Postgres en el MVP.
- **Contenido del Vector**: Un resumen del sector, tipo de licitacion y los primeros requisitos clave.

## Flujo de Trabajo

1.  **Registro de Outcome**: Cuando una licitación se cierra o el usuario marca el resultado final vía API (`POST /api/v1/experience/outcome`), el sistema:
    - Guarda los metadatos en Postgres.
    - Vectoriza el resumen del caso en ChromaDB.
2.  **Recuperación en Análisis**: Al iniciar `AnalystAgent` o `ComplianceAgent`:
    - El sistema realiza una búsqueda semántica (`find_similar`) contra el `experience_index`.
    - Si se encuentran casos con alta similitud, se inyectan en el prompt como "CONTEXTO EXPERIENCIA".
3.  **Degradación Elegante**: Si no hay casos previos, el sistema opera normalmente sin inyectar ruido (disclaimer de "Baja señal").

## Configuración y Flags

- `EXPERIENCE_LAYER_ENABLED`: Activa/Desactiva toda la Phase 5.
- `EXPERIENCE_PROMPT_INJECTION`: Si está en `False`, no se altera el prompt de los agentes (solo se calcula internamente).
- `EXPERIENCE_SHADOW_MODE`: Si está en `True`, el sistema recupera experiencia y la registra en logs, pero **no** la inyecta en el prompt enviado al LLM (ideal para validar relevancia sin alterar resultados).
- `EXPERIENCE_TOP_K`: Número de casos similares a recuperar.

## Límites y Ética
- **Privacidad**: Solo se deben indexar metadatos genéricos y requisitos públicos. No se debe almacenar información sensible de propuestas técnicas específicas sin anonimizar.
- **No es Sustituto**: La experiencia es solo una "alerta histórica". Los agentes deben priorizar siempre lo que digan las bases actuales de la licitación en curso.
