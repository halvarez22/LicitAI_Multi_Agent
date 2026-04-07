# AGENTS_CONTEXT — Referencia Operativa Compartida de LicitAI

> **Documento maestro para todos los agentes de IA que colaboran en este proyecto (desarrollo, auditoría y pruebas).**
> Todo agente nuevo (Claude, Cursor, Antigravity u otro) debe leer este archivo al inicio de cada sesión.
> Este documento define el contexto técnico, estándares, flujo y criterios mínimos de calidad esperados.
> Última actualización: 2026-03-31.

---

## 1. Identidad y Objetivos del Proyecto

**Nombre:** LicitAI — Forensic & Compliance Multi-Agent System

**Propósito:** Sistema multi-agente para la extracción, análisis y auditoría forense de licitaciones públicas y privadas. Genera dictámenes de cumplimiento normativo comparando requisitos contra documentos entregados por los participantes.

**Sector:** Compliance, procurement auditing, forensic document analysis.

---

## 2. Agentes y Colaboración

| Agente | Rol actual (ajustable) | ID interno |
|---|---|---|
| **Claude** | Revisión de cumplimiento, arquitectura y consistencia transversal. | `claude` |
| **Antigravity** | Implementación técnica avanzada y resolución de cambios complejos. | `antigravity` |
| **Cursor** | Implementación ágil, soporte de integración y validación técnica. | `cursor` |
| **Orquestador** (software) | Agente 0 del pipeline — coordina y encadena los agentes del flujo. | `orchestrator_001` |

### Política de Flexibilidad de Roles
- Los roles de agentes humanos/asistentes son **dinámicos** y pueden cambiar por decisión del responsable del proyecto.
- Ningún rol se considera permanente; lo **obligatorio** es cumplir este contexto técnico y las reglas de calidad.
- Ante conflicto de criterio entre agentes, prevalece: **seguridad + integridad de datos + cumplimiento de contratos**.

---

## 3. Pipeline de Análisis Forense (Flujo de Agentes Software)

El sistema ejecuta un pipeline en esta secuencia:

```
[PDF Entrada]
    │
    ▼
┌─────────────────────┐
│ Intake / VisionExtractor │ ← Agente 1: Extracción de datos de PDFs (escaneados y nativos)
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Analyst Agent      │ ← Agente 2: Comprensión de bases y extracción de requisitos
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Compliance Agent    │ ← Agente 3: Auditoría forense — compara requisitos vs documentos
│  (Forensic)         │    Identifica riesgos, faltantes. Mitiga "Lost in the Middle".
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Economic Agent      │ ← Agente 4: Evaluación económica
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│ Generation Agents   │ ← TechnicalWriter → Formats → EconomicWriter → Packager → Delivery
└─────────────────────┘
```

### Agentes de Generación (post-compliance):
- **TechnicalWriterAgent** — Genera documentación técnica
- **FormatsAgent** — Aplica formatos normativos exigidos por la licitación y el formato técnico interno de entrega del sistema
- **EconomicWriterAgent** — Genera análisis económico escrito
- **DocumentPackagerAgent** — Ensambla el paquete final
- **DeliveryAgent** — Gestiona la entrega

### Agentes de Soporte:
- **ValidatorAgent** — Valida y reflexiona sobre resultados
- **CriticAgent** — Decide si se requiere backtracking
- **DataGapAgent** — Detecta gaps de información
- **ChatbotRAGAgent** — RAG chatbot para consultas

---

## 4. Comunicación entre Agentes

### Model Context Protocol (MCP)
- **MCPContextManager** (`backend/app/agents/mcp_context.py`) controla el flujo y persistencia de contexto entre agentes.
- Todos los agentes deben usar `MCPContextManager` para guardar y recuperar estado de sesión.
- Versionado de estado: `SessionStateV1` con schema_version=1.
- Migración automática de estados legacy (v0 → v1).

Ejemplo operativo real (async):
```python
# 1) Recuperar contexto global (incluye session_state v1 y documentos)
context = await mcp_context_manager.get_global_context(session_id)
state_dict = context["session_state"]

# 2) Registrar completitud de tarea (vía helper recomendado)
await mcp_context_manager.record_task_completion(
    session_id=session_id,
    task_name="compliance",
    result=compliance_output
)

# 3) O persistir cambios manuales en el estado directamente vía memory
state_dict["status"] = "generation_in_progress"
await mcp_context_manager.memory.save_session(session_id, state_dict)
```

Regla técnica:
- El estado de sesión se maneja como un `dict` versionado v1 en el pipeline.
- No existen campos `last_agent` o `agent_outputs` directos en `SessionStateV1`; los resultados se inyectan en `tasks_completed`.
- Siempre usar `mcp_context_manager.record_task_completion` para asegurar trazabilidad.

### Bus de Mensajería
- **RedisAgentBus** (`backend/app/agents/communication/redis_bus.py`) pub/sub para mensajes entre agentes.
- Tipos de mensajes: `VALIDATION_NOTE`, `AGENT_OUTPUT`, etc.

### Backtracking
- Si `ValidatorAgent` + `CriticAgent` detectan calidad insuficiente, el `Orchestrator` re-ejecuta stages con hints de corrección.
- Controlado por `BACKTRACKING_ENABLED` en settings.

---

## 5. Estándares de Calidad Obligatorios

### SQA — Software Quality Assurance
- Todo código nuevo debe cumplir con las reglas de calidad definidas en este documento.
- Code reviews obligatorios antes de merge.
- Type hints obligatorios en **todo** el código Python.
- Docstrings en **español** siguiendo el **Google Style Guide** con descripción de entrada/salida y excepciones.
- Uso de `black` y `isort` para formateo automático.
- Control de calidad estricto para evitar alucinaciones en el Compliance Agent.
- Cada cambio debe acompañarse de evidencia mínima de validación (prueba local, test automatizado o checklist de verificación).

### ISO/IEC 27034 — Security in Applications
- La información sensible (empresas, licitaciones, datos personales) debe manejarse según los controles de acceso definidos.
- Logging de auditoría para toda operación que modifique estado de sesión.
- Sanitización rigurosa de Pydantic → SQLAlchemy para evitar inyección.
- No exponer datos de empresa en logs de producción.

---

## 6. Infraestructura y Runtime

### Docker (docker-compose.yml en raíz)
| Servicio | Puerto | Imagen |
|---|---|---|
| `vector-db` (ChromaDB) | 8000 | chromadb/chroma:0.4.24 |
| `database` (PostgreSQL) | 5432 | postgres:15-alpine |
| `queue-redis` (Redis) | 6379 | redis:7-alpine |
| `backend` (FastAPI) | 8000 → 8001 | Dockerfile en `./backend` |
| `frontend` (React/Vite) | 8504 | Dockerfile en `./frontend` |

- OCR y LLM Inference **corren en el host** (no en contenedores) para estabilidad y VRAM.
- Se conectan via `host.docker.internal:11434` (Ollama).
- **Comando local:** `docker-compose up -d --build`
- **Logs backend:** `docker-compose logs -f backend`

### LLM — Ollama (Local, Open Source)
- **Endpoint:** `http://localhost:11434` (host) / `http://host.docker.internal:11434` (contenedores)
- **Modelo principal:** `llama3.1:8b`
- **Modelos disponibles:** `qwen2.5-coder`, `llama3`, etc.
- Configurable via variable `OLLAMA_MODEL` en `.env`.

### Base de Datos
- **PostgreSQL 15** — persistencia de auditorías y dictámenes forenses.
- **NUNCA** perder datos de contenedor: todo se persiste en volumen Docker (`postgres_data`).
- Conexión: `DATABASE_URL=postgresql://${DB_USER:-postgres}:${DB_PASSWORD:-postgres}@database:5432/licitaciones`

### Vector Store
- **ChromaDB** — búsqueda semántica y RAG.
- Volumen persistente en `chroma_data`.

### Variables de Entorno Clave (`.env`)
```
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1:8b
VECTOR_DB_URL=http://vector-db:8000
DATABASE_URL=postgresql://postgres:postgres@database:5432/licitaciones
REDIS_URL=redis://queue-redis:6379
MEMORY_BACKEND=postgres
EXPERIENCE_LAYER_ENABLED=true
BACKTRACKING_ENABLED=true
ADAPTIVE_ORCHESTRATOR_ENABLED=true
```

---

## 7. Hardware Disponible

> ⚠️ Actualizar según specs reales de la máquina.

| Recurso | Especificación |
|---|---|
| CPU | Intel(R) Core(TM) i9-14900HX (24 Cores / 32 Logical Processors) |
| RAM | 32 GB DDR5 |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU (8 GB VRAM Dedicada) |
| Almacenamiento | SSD NVMe (Rápida lectura/escritura para Vector DB) |
| VRAM | 8188 MB - Optimizada para llama3.1:8b y qwen2.5-coder |

- Ollama corre en el **host** para maximizar los 8 GB de VRAM disponibles.
- Los contenedores Docker comparten los recursos del host de forma dinámica.
- Nota de persistencia: la memoria no volátil relevante para operación (disco/volúmenes Docker) es `postgres_data`, `chroma_data` y `redis_data`.

---

## 8. Reglas de Código y Desarrollo

### Backend (Python)
- ✅ Type hints obligatorios con `typing`
- ✅ Docstrings en **español** (entrada, salida, excepciones)
- ✅ Persistencia en PostgreSQL (no perder datos del contenedor)
- ✅ Sanitización Pydantic → SQLAlchemy
- ❌ No usar `any` sin justificación documentada
- ❌ No agregar print() en producción — usar logging

### Frontend (React)
- ✅ Componentes con formato "Tarjeta Forense": `Ubicación + Sección + Texto Literal`
- ✅ Conteo de requisitos unificado a través de todos los componentes
- ❌ No usar TailwindCSS salvo solicitud explícita
- ❌ Vanilla CSS y componentes estructurados

### General
- ✅ Lenguaje y planificación en **español**
- ✅ Prompt engineering con few-shot learning y refuerzo positivo
- ✅ Mensajes de commit descriptivos
- ✅ Todo agente debe justificar decisiones técnicas que se desvíen de esta guía

---

## 9. Criterios de Referencia Obligatorios para Cualquier Agente

Antes de proponer o modificar código, cualquier agente debe validar:

1. **Objetivo funcional**: el cambio mejora extracción, análisis, auditoría o entrega del pipeline.
2. **Integridad de datos**: no comprometer persistencia de auditorías en PostgreSQL.
3. **Compatibilidad contractual**: respetar contratos y schemas en `backend/app/contracts/` y `backend/app/api/schemas/`.
4. **Coherencia de infraestructura**: puertos, servicios y variables alineados con `docker-compose.yml` y entorno vigente.
5. **Calidad verificable**: incluir criterio de prueba y resultados esperados.

Checklist mínimo por cambio:
- Impacto en backend/frontend/infra.
- Riesgos y mitigaciones.
- Prueba ejecutada o plan de prueba.
- Resultado esperado y criterio de aceptación.

---

## 10. Estructura del Proyecto

```
licitaciones-ai/
├── AGENTS_CONTEXT.md          ← ESTE ARCHIVO (conocimiento compartido)
├── CLAUDE.md                   ← Contexto específico para Claude
├── docker-compose.yml
├── .env.example
├── .env.dev
├── backend/
│   ├── app/
│   │   ├── agents/             ← Todos los agentes Python
│   │   │   ├── orchestrator.py
│   │   │   ├── analyst.py
│   │   │   ├── compliance.py
│   │   │   ├── economic.py
│   │   │   ├── mcp_context.py   ← MCP Manager
│   │   │   └── communication/
│   │   │       └── redis_bus.py
│   │   ├── api/                ← FastAPI routes
│   │   ├── models/             ← SQLAlchemy + Pydantic
│   │   ├── services/           ← LLM, OCR, Vector
│   │   └── core/               ← Config, logging
│   ├── Dockerfile
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── api/
│   ├── Dockerfile
│   └── package.json
├── services/
│   └── (servicios adicionales)
├── data/                       ← Datos persistentes
├── logs/                        ← Logs de aplicación
└── scripts/
    └── init-db.sql
```

---

## 11. Flujo de Trabajo para Nuevos Agentes

1. **Leer `AGENTS_CONTEXT.md`** (este archivo) — comprender el proyecto completo.
2. **Leer `CLAUDE.md`** — contexto específico del agente Claude.
3. **Revisar docker-compose.yml** — entender la infraestructura.
4. **Explorar `backend/app/agents/`** — entender los agentes existentes.
5. **Revisar `backend/app/agents/mcp_context.py`** — entender MCP y manejo de sesión.
6. **Ejecutar `docker-compose up -d --build`** — verificar entorno.
7. **Revisar `backend/app/contracts/`** — contratos entre agentes.

### Flujo recomendado para agentes de desarrollo y pruebas
8. **Definir alcance del cambio** (qué se toca y qué no se toca).
9. **Implementar o validar** siguiendo estándares de este documento.
10. **Ejecutar validación mínima** (tests, logs, smoke checks o evidencia equivalente).
11. **Documentar hallazgos** (riesgos, pendientes, decisiones y siguientes pasos).

---

## 12. Contratos y Schemas Clave

| Archivo | Propósito |
|---|---|
| `backend/app/contracts/session_contracts.py` | SessionStateV1, migración v0→v1 |
| `backend/app/contracts/agent_contracts.py` | AgentInput, AgentOutput, AgentStatus |
| `backend/app/contracts/orchestrator_contracts.py` | OrchestratorState |
| `backend/app/api/schemas/requests.py` | Esquemas de request API |
| `backend/app/api/schemas/responses.py` | Esquemas de response API |

---

## 13. Configuraciones de Comportamiento (Flags)

| Flag | Descripción | Default |
|---|---|---|
| `BACKTRACKING_ENABLED` | Habilita re-ejecución con hints | `true` |
| `ADAPTIVE_ORCHESTRATOR_ENABLED` | Pipeline adaptativo | `true` |
| `ADAPTIVE_PIPELINE_SAFE_MODE` | Modo seguro del pipeline adaptativo ante condiciones de riesgo | `true` |
| `EXPERIENCE_LAYER_ENABLED` | Capa de experiencia | `true` |
| `CONFIDENCE_ENABLED` | Cálculo de confianza | `true` |
| `CONFIDENCE_SHADOW_MODE` | Ejecuta confianza en modo sombra sin impactar decisiones finales | `false` |
| `FEEDBACK_UI_ENABLED` | UI de feedback al usuario | `true` |

### Valores de `stop_reason` del Orquestador (Trazabilidad)
- `FINAL_OK`: Proceso completado exitosamente (análisis + generación).
- `ANALYSIS_COMPLETED`: Fase de análisis terminada (esperando decisión).
- `GENERATION_COMPLETED`: Fase de generación terminada.
- `COMPLIANCE_ERROR`: Error crítico de cumplimiento detectado.
- `ECONOMIC_GAP`: Vacío de información económica insalvable.
- `INCOMPLETE_DATA`: Datos insuficientes para proceder.
- `INVALID_MODE`: Modo de operación no soportado.
- `INVALID_INPUT`: Inputs de sesión malformados o faltantes.
- `LOW_CONFIDENCE`: Confianza por debajo del umbral mínimo.

---

## 14. Contacto y Referencia

- **Proyecto:** LicitAI — Forensic & Compliance Multi-Agent System
- **Stack:** FastAPI + React/Vite + PostgreSQL + ChromaDB + Ollama
- **Infraestructura:** Docker + Docker Compose
- **Repositorio:** [Definir URL oficial del repositorio para trazabilidad]
- **Documentación adicional:** `CLAUDE.md` (contexto específico)

---

## 15. Regla de Uso de Este Documento

- Este archivo es la **referencia operativa base** para cualquier agente incorporado al proyecto.
- Si existe contradicción entre instrucciones aisladas y este contexto, se debe:
  1) señalar la contradicción,  
  2) proponer ajuste,  
  3) obtener confirmación del responsable del proyecto.
- Toda actualización relevante del stack, pipeline, contratos o reglas debe reflejarse aquí en la misma iteración de cambio.

---

## 16. Plantilla Estándar de Reporte de Agente (Cierre de Tarea)

Todo agente debe cerrar su intervención con este formato mínimo:

```
[REPORTE_AGENTE]
Agente: <nombre_agente>
Objetivo: <qué se buscaba resolver>
Cambios realizados: <lista breve de archivos/componentes tocados>
Validación ejecutada: <tests, smoke checks, logs o evidencia aplicada>
Resultado: <exitoso/parcial/fallido + razón breve>
Riesgos/Pendientes: <riesgos detectados o "ninguno">
Siguiente paso recomendado: <acción concreta>
```

Notas:
- Si no hubo cambios de código, indicar explícitamente: `Cambios realizados: ninguno`.
- Si la validación no pudo ejecutarse, indicar bloqueo y cómo destrabarlo.

> ⚠️ **Regla sine qua non:** Todo código debe cumplir SQA e ISO/IEC 27034. No comprometer datos de auditoría. Persistir siempre en PostgreSQL. Type hints y docstrings en español obligatorios.
