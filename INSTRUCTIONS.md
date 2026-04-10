# LicitAI - Reglas de Ingeniería Operativa

## Arquitectura Base
- **Backend:** Python 3.11+, FastAPI. Priorizar I/O asíncrono (`async def`) en fronteras de red/disco.
- **Frontend:** React + Vite en `frontend/`. Usar CSS estructurado; **no usar TailwindCSS** salvo solicitud explícita del equipo.
- **Contratos estrictos:** Las entradas/salidas entre agentes deben respetar modelos tipados (por ejemplo `AgentInput`, `AgentOutput`, `LLMResponse`, `AgentStatus`).

## Condición Sine Qua Non (Inviolable)
1. **SQA:** Todo cambio nuevo debe cubrir regresión técnica mínima (tests focalizados) y mantener legibilidad de nivel productivo.
2. **Seguridad (alineación ISO/IEC 27034):** Evitar exposición de detalles internos en respuestas HTTP. Errores detallados van a logs internos.
3. **Integración MCP:** Mantener la capa de contexto/memoria MCP como contrato de interoperabilidad de agentes.

## Protocolo de Arquitectura y Mantenimiento
**Regla de oro:** Bajo acoplamiento y responsabilidad única. Evitar módulos monolíticos y cambios colaterales sin aislamiento.

### 1) Estructura de archivos
- **Atomicidad:** Cada módulo debe tener una responsabilidad principal clara.
- **Tamaño razonable:** Si una función crece excesivamente, extraer helpers/coordinadores.

### 2) Mantenimiento seguro
- **Cápsula de cambio:** Mapear dependencias antes de editar.
- **No romper lo operativo:** Preferir extensiones compatibles sobre cambios destructivos del core.

### 3) Verificación obligatoria
- Validar contratos de integración (APIs, eventos internos, llamadas entre agentes).
- Registrar decisiones relevantes de arquitectura en `MEMORY.md`.

## Estándares de Agentes
1. **Contratos inviolables:** Evitar `dict` ad-hoc cuando existe contrato en `app.contracts`.
2. **RAG resiliente:** Usar los clientes/capas de resiliencia del proyecto, no integraciones crudas directas.
3. **Compliance gatekeeper:** Mantener evidencia trazable y validación estricta por zonas.
4. **Eficiencia de recursos:** Optimizar chunking/procesamiento para entorno local limitado.

## Reglas de codificación
- Si una tarea implica refactor central (`orchestrator`, `economic`, `compliance`), pedir confirmación antes de cambios amplios.
- Nunca devolver trazas internas completas al cliente HTTP; registrar detalle técnico en logs.
