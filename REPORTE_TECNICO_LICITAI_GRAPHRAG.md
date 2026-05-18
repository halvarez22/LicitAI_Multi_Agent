# REPORTE TECNICO DETALLADO — LicitAI
## Analisis para Evaluacion de Integracion con GraphRAG

**Version:** 1.0 | **Fecha:** Mayo 2026 | **Proposito:** Analisis de potenciacion con Microsoft GraphRAG

---

## 1. IDENTIDAD Y PROPOSITO DEL SISTEMA

**Nombre:** LicitAI — Forensic and Compliance Multi-Agent System

**Dominio:** Procurement compliance, auditoria forense de licitaciones publicas mexicanas (LAASSP / LOPSRM / CompraNet).

**Proposito central:** Automatizar el ciclo completo de participacion en licitaciones publicas:
1. Extraccion de requisitos desde bases de licitacion (PDFs escaneados o nativos)
2. Auditoria forense de cumplimiento normativo (empresa vs. requisitos)
3. Evaluacion de viabilidad de participacion (semaforo Go/No-Go)
4. Generacion automatica del paquete completo de propuesta (tecnica + administrativa + economica)
5. Validacion y empaquetado para entrega en CompraNet

---

## 2. STACK TECNOLOGICO COMPLETO

| Capa | Tecnologia | Version | Rol |
|------|-----------|---------|-----|
| API Framework | FastAPI | 0.110.0 | REST API, routing, background tasks |
| ORM | SQLAlchemy | 2.0.27 | Modelos de datos, queries |
| Migraciones | Alembic | — | Versionado de esquema DB |
| Base de datos | PostgreSQL | 15 | Persistencia de auditorias, sesiones, empresas |
| Vector DB | ChromaDB | 0.4.24 | Busqueda semantica RAG, indexacion de documentos |
| Cache/Queue | Redis | 7 | Job queue, pub/sub entre agentes, caching |
| LLM (local) | Ollama | — | Inferencia LLM local (llama3.1:8b, qwen2.5-coder) |
| OCR | PyMuPDF | 1.23.26 | Extraccion de texto de PDFs |
| OCR complementario | pdf2image + Pillow | — | PDFs escaneados |
| Procesamiento | Pandas + NumPy | — | Analisis de datos tabulares |
| Fuzzy matching | RapidFuzz | — | Deduplicacion y normalizacion de texto |
| Logging | Structlog | 24.1.0 | Logging estructurado JSON |
| Testing | Pytest + Hypothesis | 8.0.2 / 6.100.0 | Tests unitarios + property-based |
| Frontend | React + Vite | — | UI de analisis, decision y descarga |
| Orquestacion | Docker Compose | — | Contenedores de servicios |
| Generacion DOCX | python-docx | — | Documentos Word |
| Generacion XLSX | openpyxl | — | Hojas de calculo |
| Generacion PDF | ReportLab | — | Checklists y guias de entrega |
| Templates legales | Jinja2 | — | Plantillas de documentos normativos |
| Hashing | hashlib SHA-256 | stdlib | Integridad de archivos CompraNet |

### Hardware de Produccion

| Recurso | Especificacion |
|---------|---------------|
| CPU | Intel Core i9-14900HX (24 cores / 32 logicos) |
| RAM | 32 GB DDR5 |
| GPU | NVIDIA RTX 4060 Laptop (8 GB VRAM) |
| Almacenamiento | SSD NVMe |
| LLM | Ollama en host (maximiza VRAM), llama3.1:8b |

### Servicios Docker

| Servicio | Puerto | Imagen |
|---------|--------|--------|
| ChromaDB (vector-db) | 8000 | chromadb/chroma:0.4.24 |
| PostgreSQL (database) | 5432 | postgres:15-alpine |
| Redis (queue-redis) | 6379 | redis:7-alpine |
| FastAPI (backend) | 8001 | Dockerfile local |
| React (frontend) | 8504 | Dockerfile local |


---

## 3. ARQUITECTURA DE AGENTES

### 3.1 Pipeline Principal (11 Agentes)

`
[PDF Bases de Licitacion]
         |
         v
[STAGE 1] INTAKE / VISION EXTRACTOR
  - OCR via PyMuPDF + pdf2image
  - Chunking y embedding de fragmentos
  - Indexacion en ChromaDB (coleccion por session_id)
  - Tiempo: ~1-2 min por PDF
         |
         v
[STAGE 2] ANALYST AGENT (v2 Enhanced)
  - 8+ busquedas semanticas multidimensionales en ChromaDB
  - Extrae: cronograma, requisitos, garantias, criterios evaluacion,
    reglas economicas, alcance operativo
  - NUEVO: solvencia tecnica (experiencia, personal, equipos, normas)
  - NUEVO: condiciones contractuales (tipo contrato, penalizaciones, pagos)
  - NUEVO: checklist consolidado ordenado por prioridad
  - Confidence scoring por extraccion
  - Tiempo: ~2-3 min
         |
         v
[STAGE 3] COMPLIANCE AGENT (Map-Reduce v5.0)
  - Barrido de 4 zonas: Administrativo/Legal, Tecnico/Operativo,
    Formatos/Anexos, Garantias/Seguros
  - MAP: Extraccion paralela por bloques de texto (LLM)
  - REDUCE: Deduplicacion por fingerprint SHA-256, normalizacion
  - Clasificacion por match_tier: literal / normalized / weak / none
  - Matriz Must-Have (triage normativo por ley y categoria)
  - Deteccion de causas de desechamiento
  - Score de confianza agregado por zona
  - Tiempo: ~10-15 min
         |
         v
[STAGE 4] COMPLIANCE GATE (Determinista v12.1)
  - Evaluacion de causas de descalificacion (knock-outs)
  - Corte de pipeline si hay causas criticas
  - Sin LLM — logica determinista pura
  - Tiempo: <1 segundo
         |
         v
[STAGE 5] GO/NO-GO AGENT (Semaforo)
  - Deteccion de brechas: empresa vs. requisitos de bases
  - Categorias: certificacion_faltante, capital_insuficiente,
    experiencia_insuficiente, documento_faltante, requisito_no_acreditado
  - Semaforo: RED (knock-outs) / YELLOW (brechas) / GREEN
  - Score de cumplimiento tecnico (0-100, determinista)
  - PAUSA para decision del usuario si RED o YELLOW
  - Tiempo: <5 segundos
         |
    [Usuario autoriza override]
         |
         v
[STAGE 6] ECONOMIC AGENT
  - Evaluacion de precios unitarios
  - Calculo de propuesta economica (partidas, IVA, totales)
  - Deteccion de gaps economicos
  - Tiempo: ~2-3 min
         |
         v
[STAGE 7] GENERATION PIPELINE (6 agentes secuenciales)
  7a. TechnicalWriterAgent  -> Propuesta tecnica (DOCX)
  7b. FormatsAgent          -> Documentos administrativos (DOCX)
  7c. EconomicWriterAgent   -> Propuesta economica (XLSX + DOCX)
  7d. DocumentPackagerAgent -> Organizacion en sobres + caratulas
  7e. CompraNetPackager     -> Validacion ext + SHA-256 + ZIP
  7f. DeliveryAgent         -> Checklist final (PDF) + guia de entrega
  Tiempo: ~5-10 min total
         |
         v
[Paquete ZIP descargable + Manifiesto SHA-256 + Checklist PDF]
`

### 3.2 Catalogo Completo de Agentes

| Agente | ID | Archivo | Rol | Patron |
|--------|-----|---------|-----|--------|
| OrchestratorAgent | orchestrator_001 | orchestrator.py | Coordinador central del pipeline | Adaptive Pipeline |
| AnalystAgent | analyst_001 | analyst.py | Extraccion de requisitos de bases | RAG + LLM |
| ComplianceAgent | compliance_001 | compliance.py | Auditoria forense Map-Reduce | Map-Reduce + LLM |
| ComplianceGate | gate_001 | compliance_gate.py | Evaluacion determinista de knock-outs | Determinista |
| GoNoGoAgent | go_no_go_001 | go_no_go.py | Semaforo de decision | Determinista |
| EconomicAgent | economic_001 | economic.py | Evaluacion economica | RAG + LLM |
| TechnicalWriterAgent | tech_writer_001 | technical_writer.py | Propuesta tecnica DOCX | LLM + Templates |
| FormatsAgent | formats_001 | formats.py | Documentos administrativos DOCX | LLM + Jinja2 |
| EconomicWriterAgent | econ_writer_001 | economic_writer.py | Propuesta economica XLSX/DOCX | Templates |
| DocumentPackagerAgent | packager_001 | document_packager.py | Organizacion en sobres | LLM + Fallback |
| CompraNetPackager | compranet_001 | packager.py | Validacion CompraNet + SHA-256 | Determinista |
| DeliveryAgent | delivery_001 | delivery.py | Checklist PDF + guia entrega | LLM + ReportLab |
| ValidatorAgent | validator_001 | validator.py | Valida calidad de outputs | Reflexion |
| CriticAgent | critic_001 | critic.py | Decide si se requiere backtracking | Reflexion |
| DataGapAgent | datagap_001 | data_gap.py | Detecta datos faltantes del perfil | Determinista |
| ChatbotRAGAgent | chatbot_001 | chatbot_rag.py | RAG conversacional + recoleccion datos | RAG + LLM |

### 3.3 Servicios de Infraestructura

| Servicio | Archivo | Rol |
|---------|---------|-----|
| MCPContextManager | mcp_context.py | Persistencia versionada de sesion (PostgreSQL) |
| ResilientLLMClient | resilient_llm.py | Cliente LLM con reintentos exponenciales |
| VectorDbServiceClient | vector_db.py | Busqueda semantica en ChromaDB |
| RedisAgentBus | communication/redis_bus.py | Pub/sub entre agentes |
| ConfidenceScorer | confidence_scorer.py | Calculo de confianza de extracciones |
| ExperienceStore | experience_store.py | Busqueda de casos similares (Fase 5) |
| LegalTemplateEngine | template_engine.py | Render de templates Jinja2 con verificacion de integridad |
| ValidationMappingService | validation_service.py | Mapeo de errores de validacion |


---

## 4. MODELOS DE DATOS CLAVE

### 4.1 SessionStateV1 (Estado de Sesion — PostgreSQL)

`json
{
  "schema_version": 1,
  "status": "initialized | analysis_in_progress | compliance_completed | go_no_go_pending | generation_in_progress | completed",
  "global_inputs": { "session_id": "LA-050GYR019-E123-2024", "company_id": "empresa_001" },
  "tasks_completed": [
    { "task": "stage_completed:analysis", "result": { "data": { "cronograma": {}, "requisitos_participacion": [] } } },
    { "task": "stage_completed:compliance", "result": { "data": { "administrativo": [], "tecnico": [], "formatos": [], "audit_summary": {} } } },
    { "task": "go_no_go_result", "result": { "data": { "semaforo": "YELLOW", "brechas": [], "score_cumplimiento_tecnico": 75 } } },
    { "task": "economic_proposal", "result": { "data": { "items": [], "currency": "MXN" } } },
    { "task": "formats_generation_COMPLETED", "result": { "data": { "documentos": [], "count": 5 } } }
  ],
  "generation_state": {
    "status": "running | completed | failed | waiting_for_data",
    "jobs": [
      { "id": "technical", "type": "agent", "status": "completed" },
      { "id": "formats", "type": "agent", "status": "running" },
      { "id": "economic_writer", "type": "agent", "status": "pending" }
    ]
  },
  "go_no_go_result": {
    "semaforo": "RED | YELLOW | GREEN",
    "brechas": [
      {
        "id": "uuid-v4",
        "categoria": "certificacion_faltante",
        "descripcion": "ISO 9001 no vigente",
        "requisito_bases": "Certificacion ISO 9001 vigente requerida",
        "valor_empresa": null,
        "is_knockout": true,
        "zona_origen": "TECNICO/OPERATIVO"
      }
    ],
    "total_knockouts": 1,
    "total_brechas": 3,
    "score_cumplimiento_tecnico": 75,
    "score_detalle": [],
    "requires_user_decision": true,
    "schema_version": 1
  },
  "go_no_go_override": {
    "authorized_by": "user",
    "timestamp": "2026-04-01T12:00:00Z",
    "brechas_autorizadas": ["uuid-1", "uuid-2"],
    "ip_hash": "sha256-hash-de-la-ip"
  },
  "pending_questions": [
    {
      "field": "rfc",
      "label": "RFC de la empresa",
      "question": "Cual es el RFC oficial de la empresa?",
      "document_hint": "Cedula de Identificacion Fiscal (CIF)",
      "type": "profile"
    }
  ],
  "triage_context": {
    "law": "LAASSP | LOPSRM",
    "tender_category": "BIENES | SERVICIOS | OBRA",
    "must_have_policy": {},
    "taxonomy_allowlist": []
  }
}
`

### 4.2 Compliance Master List (Output del ComplianceAgent)

`json
{
  "administrativo": [
    {
      "id": "AD-01",
      "nombre": "RFC",
      "descripcion": "Registro Federal de Contribuyentes vigente",
      "snippet": "Presentar RFC vigente ante el SAT",
      "categoria": "administrativo",
      "tipo_accion": "presentar_fisico | generar | informativo",
      "match_tier": "literal | normalized | weak | none",
      "evidence_match": true,
      "zona_origen": "ADMINISTRATIVO/LEGAL",
      "quality_flags": ["high_confidence", "literal_match"]
    }
  ],
  "tecnico": [],
  "formatos": [],
  "garantias": [],
  "audit_summary": {
    "zones": [],
    "tier_stats": { "literal": 45, "normalized": 12, "weak": 3, "none": 0 },
    "global_match_pct": 94.5,
    "total_items": 60,
    "causas_desechamiento": []
  }
}
`

### 4.3 Master Profile (Perfil de Empresa — PostgreSQL)

`json
{
  "razon_social": "Empresa SA de CV",
  "rfc": "EMP123456XYZ",
  "representante_legal": "Juan Perez Garcia",
  "domicilio_fiscal": "Calle 123, Col. Centro, CDMX, CP 06000",
  "tipo": "moral | fisica",
  "logo": "/path/to/logo.png",
  "ciudad": "Ciudad de Mexico",
  "giro": "Servicios de limpieza industrial",
  "anos_experiencia": "10",
  "numero_empleados": "150",
  "capital_contable": "5000000",
  "certificaciones": ["ISO 9001:2015", "ISO 14001:2015"],
  "contratos_similares": [
    { "cliente": "IMSS", "monto": "2,500,000 MXN", "anio": "2023" }
  ]
}
`

### 4.4 Analyst Output (Extraccion de Bases — Campos Nuevos)

`json
{
  "solvencia_tecnica": {
    "experiencia_minima": {
      "anos_experiencia": "5",
      "monto_minimo": "1,000,000 MXN",
      "numero_contratos": "3",
      "unidad_monetaria": "MXN",
      "confianza": 0.92
    },
    "plantilla_personal": [
      { "puesto": "Supervisor", "cantidad": "2", "cedula_requerida": true, "certificaciones": ["NOM-001"] }
    ],
    "normas_certificaciones": [
      { "norma": "ISO 9001", "tipo": "ISO", "vigencia_requerida": true }
    ],
    "referencias": {
      "contratos_minimos": "3",
      "antiguedad_maxima_meses": "36",
      "cartas_referencia_aceptadas": true
    }
  },
  "condiciones_contractuales": {
    "tipo_contrato": { "tipo": "precio fijo", "modalidad": "cerrado", "fuente": "explicito" },
    "penalizaciones": {
      "atraso": { "porcentaje": "1%", "periodo": "dia natural" },
      "limite_maximo": "10%"
    },
    "pagos": {
      "anticipo": { "porcentaje": "30%", "garantia_porcentaje": "30%" },
      "estimaciones": { "periodicidad": "mensual" }
    },
    "garantia_cumplimiento": { "monto_porcentaje": "10%", "tipo": "fianza", "vigencia_meses": "12" }
  },
  "checklist_consolidado": [
    {
      "id": "req_001",
      "categoria": "solvencia_tecnica",
      "subcategoria": "experiencia",
      "descripcion": "Acreditar 5 anos de experiencia en contratos similares",
      "clasificacion": "obligatorio",
      "pagina": "15",
      "clausula": "8.3",
      "orden_entrega": 1,
      "confianza": 0.92
    }
  ]
}
`

---

## 5. APIS Y ENDPOINTS

### 5.1 Endpoints Principales

| Endpoint | Metodo | Proposito |
|----------|--------|----------|
| /api/v1/health | GET | Health check |
| /api/v1/agents/process | POST | Ejecutar pipeline completo |
| /api/v1/agents/jobs/{job_id}/status | GET | Estado de job asincrono |
| /api/v1/upload | POST | Cargar PDF/DOCX de bases |
| /api/v1/sessions | GET/POST | Gestion de sesiones |
| /api/v1/sessions/{id} | GET/PUT/DELETE | CRUD de sesion |
| /api/v1/companies | GET/POST | Gestion de empresas |
| /api/v1/companies/{id} | GET/PUT | CRUD de empresa |
| /api/v1/downloads/list | GET | Listar archivos generados |
| /api/v1/downloads/file | GET | Descargar archivo individual |
| /api/v1/downloads/zip | GET | Descargar ZIP completo |
| /api/v1/chatbot/query | POST | Consultas RAG conversacional |
| /api/v1/go-no-go/{session_id}/authorize | POST | Autorizar brechas Go/No-Go |
| /api/v1/feedback | POST | Feedback HITL del usuario |
| /api/v1/experience | GET | Consultar casos similares |

### 5.2 Modos de Operacion del Pipeline

| Modo | Descripcion |
|------|-------------|
| full | Ejecuta todo el pipeline: analysis + compliance + economic + generation |
| analysis_only | Solo extraccion y compliance, sin generacion |
| generation | Ejecuta desde economic hasta generation |
| generation_only | Solo generacion, reutiliza datos de compliance ya persistidos |

### 5.3 Stop Reasons del Orquestador

| stop_reason | Significado |
|-------------|-------------|
| FINAL_OK | Proceso completado exitosamente |
| ANALYSIS_COMPLETED | Fase de analisis terminada, esperando decision |
| GENERATION_COMPLETED | Fase de generacion terminada |
| GO_NO_GO_PENDING | Semaforo RED o YELLOW, esperando autorizacion del usuario |
| COMPLIANCE_ERROR | Error critico de cumplimiento detectado |
| ECONOMIC_GAP | Vacio de informacion economica insalvable |
| INCOMPLETE_DATA | Datos insuficientes para proceder |
| INVALID_MODE | Modo de operacion no soportado |
| LOW_CONFIDENCE | Confianza por debajo del umbral minimo |


---

## 6. PATRONES DE DISENO Y ARQUITECTURA

### 6.1 Patrones Arquitectonicos

| Patron | Donde se aplica | Proposito |
|--------|----------------|----------|
| Multi-Agent Orchestration | OrchestratorAgent | Coordinacion de 16+ agentes especializados |
| Adaptive Pipeline | PipelineConfigurator | Configuracion dinamica de stages segun complejidad |
| Map-Reduce | ComplianceAgent v5.0 | Procesamiento paralelo de zonas documentales |
| Backtracking | ValidatorAgent + CriticAgent | Re-ejecucion con hints cuando calidad es insuficiente |
| HITL (Human-in-the-Loop) | GoNoGoAgent + ChatbotRAGAgent | Pausa para decision humana en puntos criticos |
| RAG (Retrieval-Augmented Generation) | AnalystAgent, ComplianceAgent, ChatbotRAGAgent | Busqueda semantica + generacion LLM |
| Event Sourcing | tasks_completed en SessionStateV1 | Historial inmutable de completitud de stages |
| CQRS | API endpoints | Separacion de comandos (process) y queries (status) |
| Quality Gates | ComplianceGate, DocumentQualityGate, FillQualityGate | Puntos de control de calidad en el pipeline |
| Graceful Degradation | ResilientLLMClient, fallbacks deterministas | Continuidad cuando LLM falla |

### 6.2 Patrones de Datos

| Patron | Descripcion |
|--------|-------------|
| Evidence Grounding | Cada requisito incluye snippet literal del documento fuente |
| Match Tier Hierarchy | literal -> normalized -> weak -> none (confianza decreciente) |
| Taxonomia Anclada | Matriz Must-Have por ley (LAASSP/LOPSRM) y categoria (BIENES/SERVICIOS/OBRA) |
| Confidence Metadata | Cada extraccion incluye score de confianza y quality_flags |
| Forensic Traceability | zona_origen, match_tier, evidence_match en cada item |
| Canonical Deduplication | SHA-256 fingerprint para identificar duplicados entre zonas |
| Schema Versioning | SessionStateV1 con migracion automatica v0->v1 |

### 6.3 Flags de Comportamiento Configurables

| Flag | Descripcion | Default |
|------|-------------|---------|
| BACKTRACKING_ENABLED | Habilita re-ejecucion con hints | true |
| ADAPTIVE_ORCHESTRATOR_ENABLED | Pipeline adaptativo | true |
| ADAPTIVE_PIPELINE_SAFE_MODE | Modo seguro ante condiciones de riesgo | true |
| EXPERIENCE_LAYER_ENABLED | Capa de experiencia (casos similares) | true |
| CONFIDENCE_ENABLED | Calculo de confianza | true |
| CONFIDENCE_SHADOW_MODE | Ejecuta confianza sin impactar decisiones | false |
| FEEDBACK_UI_ENABLED | UI de feedback al usuario | true |
| ENHANCED_EXTRACTION_ENABLED | Extraccion de solvencia tecnica y condiciones contractuales | true |
| DOCUMENT_QUALITY_HARD_GATE_ENABLED | Gate duro para frenar sobre-generacion | true |

---

## 7. GRAFO DE CONOCIMIENTO IMPLICITO (CRITICO PARA GRAPHRAG)

Este es el analisis mas importante para la evaluacion de GraphRAG.
LicitAI ya construye y consume un grafo de conocimiento implicito,
pero lo materializa como busqueda vectorial plana en ChromaDB.
GraphRAG permitiria materializar y explotar ese grafo explicitamente.

### 7.1 Entidades del Dominio

`
ENTIDADES PRINCIPALES:
|
+-- Licitacion (session_id)
|   +-- Numero de licitacion
|   +-- Convocante (dependencia gubernamental)
|   +-- Ley aplicable (LAASSP / LOPSRM)
|   +-- Categoria (BIENES / SERVICIOS / OBRA)
|   +-- Cronograma (fechas clave)
|   +-- Modalidad (publica / restringida / directa)
|
+-- Empresa (company_id)
|   +-- Razon social / RFC
|   +-- Representante legal
|   +-- Certificaciones vigentes (ISO 9001, ISO 14001, NOM-xxx)
|   +-- Experiencia (contratos similares con montos y clientes)
|   +-- Capital contable
|   +-- Plantilla de personal (puestos, cedulas, certificaciones)
|   +-- Giro / actividad economica
|
+-- Requisito (id: AD-01, TC-05, etc.)
|   +-- Nombre / Descripcion
|   +-- Zona (Administrativo / Tecnico / Formatos / Garantias)
|   +-- Tipo de accion (generar / presentar_fisico / informativo)
|   +-- Match tier (literal / normalized / weak)
|   +-- Evidence snippet (texto literal del documento)
|   +-- Clasificacion (obligatorio / deseable / condicional)
|
+-- Brecha (id: uuid)
|   +-- Categoria (certificacion_faltante / capital_insuficiente /
|       experiencia_insuficiente / documento_faltante / requisito_no_acreditado)
|   +-- Requisito de bases (texto)
|   +-- Valor de empresa (dato del master_profile)
|   +-- Es knock-out (boolean)
|   +-- Zona de origen
|
+-- Documento Generado
|   +-- Tipo (propuesta_tecnica / administrativo / economico)
|   +-- Template usado (anexo_7 / anexo_11 / anexo_15 / etc.)
|   +-- Hash SHA-256
|   +-- Sobre de entrega (1-Administrativo / 2-Tecnico / 3-Economico)
|
+-- Caso de Experiencia (ExperienceStore)
|   +-- Licitacion similar (session_id referenciado)
|   +-- Resultado (gano / perdio / descalificado)
|   +-- Brechas detectadas en ese caso
|   +-- Score de cumplimiento tecnico historico
|
+-- Norma / Certificacion
|   +-- Identificador (ISO 9001, NOM-001, NMX-xxx)
|   +-- Tipo (ISO / NOM / NMX / otro)
|   +-- Vigencia requerida
|
+-- Convocante (dependencia)
    +-- Nombre oficial
    +-- Tipo (federal / estatal / municipal)
    +-- Historial de licitaciones
`

### 7.2 Relaciones del Dominio

`
RELACIONES CLAVE (candidatas a aristas en el grafo):

Licitacion --REQUIERE--> Requisito (1:N)
  Propiedades: zona, tipo_accion, es_knockout, clasificacion

Empresa --CUMPLE--> Requisito (N:M)
  Propiedades: match_tier, evidence_match, confidence_score

Empresa --TIENE_BRECHA--> Requisito (N:M, cuando no cumple)
  Propiedades: categoria_brecha, is_knockout, valor_empresa

Brecha --ES_KNOCKOUT_DE--> Licitacion (N:1)
  Propiedades: causa_desechamiento, zona_origen

Requisito --GENERA--> Documento (1:1 o 1:N)
  Propiedades: template_id, tipo_documento

Requisito --PERTENECE_A--> Zona (N:1)
  Propiedades: zona_nombre, orden_prioridad

Licitacion --APLICA--> Ley (N:1: LAASSP / LOPSRM)
  Propiedades: articulos_aplicables

Ley --DEFINE--> MustHavePolicy (1:1)
  Propiedades: requisitos_obligatorios_por_categoria

Empresa --PARTICIPO_EN--> Licitacion (N:M, historico)
  Propiedades: resultado, score_cumplimiento, brechas_detectadas

Licitacion --SIMILAR_A--> Licitacion (N:M, ExperienceStore)
  Propiedades: score_similitud, convocante_igual, categoria_igual

Certificacion --ACREDITA--> Requisito (N:M)
  Propiedades: nivel_acreditacion, vigencia

Contrato_Previo --EVIDENCIA--> Experiencia (N:1)
  Propiedades: monto, cliente, anio, tipo_servicio

Convocante --EMITE--> Licitacion (1:N)
  Propiedades: frecuencia, categoria_preferida

Empresa --POSEE--> Certificacion (N:M)
  Propiedades: fecha_emision, fecha_vencimiento, organismo_certificador
`

### 7.3 Limitaciones Actuales del RAG Plano (ChromaDB)

El sistema actual usa busqueda vectorial plana con estas limitaciones criticas:

1. **Sin razonamiento multi-hop**: No puede responder "que empresas con ISO 9001 ganaron
   licitaciones de servicios similares en los ultimos 2 anos?"

2. **Sin propagacion de contexto entre sesiones**: Cada licitacion es un silo.
   El ExperienceStore es rudimentario y no explota relaciones entre casos.

3. **Sin inferencia de relaciones**: No puede inferir que si una empresa tiene
   experiencia en "limpieza hospitalaria" probablemente cumple requisitos de
   "limpieza en instalaciones de salud" aunque el texto sea diferente.

4. **Sin razonamiento sobre grafos normativos**: No puede navegar la jerarquia
   LAASSP -> Articulo -> Requisito -> Documento para inferir que documentos
   son obligatorios por ley vs. por convocante.

5. **Sin deteccion de patrones de descalificacion**: No puede identificar que
   cierto tipo de convocante siempre pide ISO 9001 aunque no este explicito
   en las bases actuales.

6. **Busqueda por similitud semantica solamente**: Pierde relaciones estructurales
   entre entidades que no son capturables por embeddings.

---

## 8. FEATURES EN DESARROLLO (SPECS ACTIVAS)

### 8.1 Specs con Diseno Completo

| Spec | Estado | Descripcion |
|------|--------|-------------|
| semaforo-go-no-go | Diseno completo, implementando | Semaforo RED/YELLOW/GREEN con score determinista |
| document-generation | Diseno completo, implementando | Pipeline de 6 agentes de generacion |
| enhanced-analyst-agent | Diseno completo | Extraccion de solvencia tecnica y condiciones contractuales |
| chatbot-data-collection | Diseno completo | Recoleccion proactiva de datos faltantes via chatbot |
| datagap-enqueue-all-missing | Bugfix activo | Deteccion y encolado de todos los datos faltantes |
| auto-resolve-pending-on-upload | Diseno completo | Resolucion automatica de preguntas al subir documentos |
| session-isolation-per-tender | Bugfix activo | Aislamiento de sesiones por licitacion |
| universal-document-ingestion | Requisitos definidos | Ingesta de multiples formatos de documentos |

### 8.2 Specs Identificadas (Sin Diseno Formal Aun)

- Tender Router and Legal Audit (enrutamiento normativo)
- Economic Zero-Base Gate (validacion de propuesta economica desde cero)
- Document Quality Gate (validacion de calidad de documentos generados)
- Experience Layer v2 (mejora del ExperienceStore)

---

## 9. ANALISIS DE OPORTUNIDADES PARA GRAPHRAG

### 9.1 Que es GraphRAG y Por Que es Relevante para LicitAI

GraphRAG (Graph Retrieval-Augmented Generation) combina grafos de conocimiento
con RAG tradicional. En lugar de buscar solo por similitud vectorial, construye
un grafo explicito de entidades y relaciones, permitiendo:

- Razonamiento multi-hop sobre relaciones entre entidades
- Busqueda estructural (traversal de grafo) + semantica (embeddings)
- Inferencia de relaciones implicitas
- Respuestas a preguntas complejas que requieren combinar multiples entidades
- Deteccion de patrones en datos historicos

### 9.2 Casos de Uso de Alto Impacto para GraphRAG en LicitAI

#### CASO 1: Analisis de Brechas Inteligente (IMPACTO: CRITICO)

**Problema actual:** El GoNoGoAgent detecta brechas comparando el master_profile
contra los requisitos de la licitacion actual de forma aislada. No considera
si la empresa ha resuelto brechas similares en el pasado ni como.

**Con GraphRAG:**
- Grafo: Empresa --TUVO_BRECHA--> Requisito --EN_LICITACION--> Licitacion
- Query: "Esta empresa tuvo la misma brecha de ISO 9001 antes? La resolvio?
  Cuanto tiempo tomo? Que documento presento?"
- Resultado: Recomendacion contextualizada basada en historial real

#### CASO 2: Prediccion de Requisitos Implicitos (IMPACTO: ALTO)

**Problema actual:** El ComplianceAgent solo extrae requisitos explicitamente
mencionados en las bases. Requisitos implicitos por ley o por patron de
convocante se pierden.

**Con GraphRAG:**
- Grafo: Convocante --HISTORICAMENTE_PIDE--> Requisito (aunque no este en bases)
- Grafo: Ley --ARTICULO_X--> Requisito_Obligatorio
- Query: "Que requisitos suele pedir IMSS aunque no los mencione explicitamente?"
- Resultado: Lista de requisitos implicitos con probabilidad y fuente normativa

#### CASO 3: Similitud Semantica de Licitaciones (IMPACTO: ALTO)

**Problema actual:** El ExperienceStore es rudimentario. No puede identificar
licitaciones verdaderamente similares considerando multiples dimensiones.

**Con GraphRAG:**
- Grafo: Licitacion --SIMILAR_A--> Licitacion (por convocante, categoria, monto, requisitos)
- Query: "Que licitaciones similares a esta hemos analizado? Cuales ganamos?
  Que brechas tuvimos? Como las resolvimos?"
- Resultado: Estrategia de participacion basada en casos reales

#### CASO 4: Navegacion Normativa (IMPACTO: ALTO)

**Problema actual:** El sistema conoce la ley aplicable (LAASSP/LOPSRM) pero
no puede navegar la jerarquia normativa para inferir requisitos obligatorios
por ley que el convocante omitio mencionar.

**Con GraphRAG:**
- Grafo: LAASSP --ARTICULO_36--> Requisito_Obligatorio --APLICA_A--> Categoria_SERVICIOS
- Query: "Que documentos son obligatorios por LAASSP para licitaciones de servicios
  aunque el convocante no los mencione?"
- Resultado: Lista de requisitos legales con referencia normativa exacta

#### CASO 5: Perfil de Empresa Enriquecido (IMPACTO: MEDIO)

**Problema actual:** El master_profile es un JSON plano. No captura relaciones
entre certificaciones, experiencia y tipos de licitacion donde aplican.

**Con GraphRAG:**
- Grafo: Empresa --TIENE--> Certificacion --ACREDITA--> Requisito --EN--> Categoria
- Query: "Con las certificaciones actuales de la empresa, que tipos de licitaciones
  puede ganar sin brechas criticas?"
- Resultado: Mapa de oportunidades de licitacion para la empresa

#### CASO 6: Deteccion de Patrones de Descalificacion (IMPACTO: MEDIO)

**Problema actual:** No hay aprendizaje de patrones de descalificacion entre
licitaciones. Cada analisis empieza desde cero.

**Con GraphRAG:**
- Grafo: Empresa --FUE_DESCALIFICADA_POR--> Requisito --EN--> Licitacion --DE--> Convocante
- Query: "Que convocantes tienen requisitos que historicamente descalifican a
  empresas con el perfil de esta?"
- Resultado: Alertas tempranas de riesgo de descalificacion

### 9.3 Arquitectura Propuesta para Integracion GraphRAG

#### Opcion A: GraphRAG como Capa Adicional (Recomendada)

`
ARQUITECTURA ACTUAL:
ChromaDB (vectores) <-- AnalystAgent, ComplianceAgent, ChatbotRAGAgent

ARQUITECTURA CON GRAPHRAG:
ChromaDB (vectores) <-- Busqueda semantica (como hoy)
     +
Neo4j / Neptune (grafo) <-- Razonamiento estructural (nuevo)
     |
     v
GraphRAG Orchestrator (nuevo servicio)
  - Decide cuando usar vector search vs. graph traversal vs. hibrido
  - Combina resultados de ambas fuentes
  - Alimenta al LLM con contexto enriquecido
`

#### Opcion B: Microsoft GraphRAG (Indexacion Automatica)

Microsoft GraphRAG puede indexar automaticamente los documentos de bases
de licitacion y construir el grafo de conocimiento sin definicion manual
de esquema. Ventajas:
- Menor esfuerzo de implementacion inicial
- Descubrimiento automatico de entidades y relaciones
- Integrado con Azure OpenAI

Desventajas para LicitAI:
- Requiere Azure OpenAI (vs. Ollama local actual)
- Menor control sobre el esquema del grafo
- Costo de API por volumen de documentos

#### Opcion C: LlamaIndex + Neo4j (Hibrida, Recomendada para Produccion)

`
LlamaIndex PropertyGraphIndex
  - Extraccion de entidades y relaciones via LLM (Ollama compatible)
  - Almacenamiento en Neo4j
  - Busqueda hibrida: vector + grafo
  - Compatible con el stack actual (Python, Ollama)
`

### 9.4 Datos Existentes Aprovechables para Construir el Grafo

LicitAI ya genera datos estructurados que pueden alimentar directamente
el grafo de conocimiento:

| Dato Existente | Entidades/Relaciones que Genera |
|---------------|--------------------------------|
| compliance_master_list | Requisito, Zona, match_tier, evidence_snippet |
| go_no_go_result.brechas | Brecha, categoria, is_knockout, zona_origen |
| tasks_completed (historial) | Licitacion, stages completados, resultados |
| master_profile | Empresa, certificaciones, experiencia, personal |
| audit_summary.tier_stats | Estadisticas de cumplimiento por zona |
| session_state.triage_context | Ley aplicable, categoria, must_have_policy |
| ExperienceStore | Casos similares, resultados historicos |
| checklist_consolidado | Requisito, clasificacion, pagina, clausula |

### 9.5 Impacto Estimado por Componente

| Componente | Impacto GraphRAG | Tipo de Mejora |
|-----------|-----------------|----------------|
| AnalystAgent | ALTO | Extraccion con contexto de licitaciones similares |
| ComplianceAgent | CRITICO | Deteccion de requisitos implicitos por patron normativo |
| GoNoGoAgent | ALTO | Brechas contextualizadas con historial de resolucion |
| ChatbotRAGAgent | ALTO | Respuestas multi-hop sobre relaciones entre entidades |
| ExperienceStore | CRITICO | Reemplazar con grafo de experiencia real |
| EconomicAgent | MEDIO | Precios de referencia de licitaciones similares |
| DataGapAgent | MEDIO | Deteccion de gaps basada en patrones historicos |

---

## 10. RIESGOS Y CONSIDERACIONES TECNICAS

### 10.1 Riesgos de Integracion

| Riesgo | Probabilidad | Impacto | Mitigacion |
|--------|-------------|---------|------------|
| Latencia adicional por consultas al grafo | Alta | Medio | Cache de queries frecuentes, grafo en memoria |
| Complejidad de mantenimiento del esquema del grafo | Media | Alto | Definir esquema minimo viable, evolucion incremental |
| Inconsistencia entre grafo y vector DB | Media | Alto | Sincronizacion transaccional al indexar documentos |
| Costo de LLM para extraccion de entidades | Alta | Medio | Usar Ollama local para extraccion, solo LLM para razonamiento |
| Curva de aprendizaje del equipo | Media | Medio | Empezar con LlamaIndex que abstrae la complejidad |

### 10.2 Compatibilidad con Stack Actual

| Componente | Compatibilidad | Notas |
|-----------|---------------|-------|
| Ollama (llama3.1:8b) | COMPATIBLE | LlamaIndex soporta Ollama nativamente |
| ChromaDB | COMPATIBLE | Puede coexistir como vector store complementario |
| PostgreSQL | COMPATIBLE | Neo4j puede correr en Docker junto a PostgreSQL |
| FastAPI | COMPATIBLE | Clientes Python para Neo4j y LlamaIndex |
| Docker Compose | COMPATIBLE | Agregar servicio neo4j al compose |
| Redis | COMPATIBLE | Sin cambios necesarios |

### 10.3 Requisitos de Hardware para GraphRAG

El hardware actual (i9-14900HX, 32GB RAM, RTX 4060 8GB) es suficiente para:
- Neo4j Community Edition (grafo en memoria para datasets medianos)
- LlamaIndex con Ollama (extraccion de entidades local)
- Grafos de hasta ~100,000 nodos y ~500,000 relaciones

Para produccion con volumenes mayores se recomienda:
- Neo4j Enterprise o Amazon Neptune
- Separar el servicio de grafo del servidor de aplicacion

---

## 11. ROADMAP DE INTEGRACION RECOMENDADO

### Fase 1: Fundacion del Grafo (2-3 semanas)
- Definir esquema de grafo (entidades y relaciones del dominio)
- Instalar Neo4j en Docker Compose
- Crear GraphIngestionService que lea tasks_completed y construya el grafo
- Poblar grafo con datos historicos existentes en PostgreSQL

### Fase 2: GraphRAG en ExperienceStore (2-3 semanas)
- Reemplazar ExperienceStore actual con consultas al grafo
- Implementar busqueda de licitaciones similares via graph traversal
- Integrar resultados en GoNoGoAgent (contexto historico de brechas)

### Fase 3: Requisitos Implicitos en ComplianceAgent (3-4 semanas)
- Indexar jerarquia normativa LAASSP/LOPSRM en el grafo
- Agregar consulta al grafo en ComplianceAgent para detectar requisitos implicitos
- Validar con casos reales de licitaciones conocidas

### Fase 4: ChatbotRAG con Razonamiento Multi-Hop (2-3 semanas)
- Integrar LlamaIndex PropertyGraphIndex con ChatbotRAGAgent
- Habilitar preguntas complejas sobre relaciones entre entidades
- Implementar busqueda hibrida (vector + grafo)

### Fase 5: Prediccion y Alertas Tempranas (3-4 semanas)
- Modelos de prediccion de riesgo de descalificacion
- Alertas de requisitos implicitos por patron de convocante
- Dashboard de oportunidades de licitacion para la empresa

---

## 12. RESUMEN EJECUTIVO PARA EVALUACION DE GRAPHRAG

LicitAI es un sistema multi-agente maduro con:
- 16+ agentes especializados en un pipeline forense de licitaciones
- Grafo de conocimiento implicito ya definido (entidades y relaciones del dominio)
- Datos estructurados de alta calidad (compliance_master_list, brechas, historial)
- Stack Python compatible con las principales librerias de GraphRAG

**El sistema esta listo para GraphRAG.** Los datos ya existen y estan estructurados.
Lo que falta es materializarlos como grafo explicito y agregar la capa de
razonamiento estructural.

**Impacto esperado:**
- ComplianceAgent: +20-30% de requisitos detectados (implicitos por patron normativo)
- GoNoGoAgent: Brechas contextualizadas con historial de resolucion (reduce falsos positivos)
- ChatbotRAGAgent: Respuestas a preguntas complejas multi-hop (actualmente imposibles)
- ExperienceStore: De rudimentario a sistema de aprendizaje real entre licitaciones

**Esfuerzo estimado:** 12-16 semanas para integracion completa (Fases 1-5)
**Esfuerzo minimo viable:** 4-6 semanas para Fases 1-2 (impacto inmediato en GoNoGo y Experience)

**Tecnologia recomendada:** LlamaIndex + Neo4j + Ollama (compatible con stack actual,
sin dependencia de APIs externas, corre en hardware disponible)

---

*Reporte generado por Kiro — Mayo 2026*
*Basado en analisis exhaustivo del codebase de LicitAI v1.x*
