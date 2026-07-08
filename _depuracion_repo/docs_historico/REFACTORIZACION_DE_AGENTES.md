# REFACTORIZACIÓN DE AGENTES — LicitAI

> Documento de especificaciones de refactorización para la consolidación arquitectónica.
> Basado en el consenso tripartito (Claude + Antigravity + Cursor).
> Fecha: 2026-03-31.
> Estado: PENDIENTE DE IMPLEMENTACIÓN.

---

## 1. Taxonomy Formal de Autonomía (Niveles L1/L2/L3)

### L1 — Autonomía Decisional
Pueden cambiar el flujo o estrategia del pipeline por decisión propia.

| Agente | Razón |
|---|---|
| **Orchestrator** | Coordina, decide rutas, aplica backtracking, maneja abandono de sesión |

### L2 — Autonomía Técnica
Ejecutan su dominio con criterio interno pero NO alteran el plan global.

| Agente | Dominio | Criterio interno |
|---|---|---|
| **AnalystAgent** | Extracción de requisitos | Cómo parsear y estructurar requisitos |
| **ComplianceAgent** | Auditoría forense | Cómo evaluar cumplimiento vs requisitos |
| **EconomicAgent** | Evaluación económica | Cómo analizar costos y viabilidad |
| **Intake/VisionExtractor** | Extracción de PDFs | Cómo OCR y extraer contenido |
| **DataGapAgent** | Detección de faltantes | Qué clasificar como gap |
| **ForensicAuditor** | Juicio de calidad + veto | EVALÚA y VETA — ver sección 3 |

### L3 — Automatización Ejecutora
Transforman datos según contrato, sin criterio propio sobre el plan global.

| Agente (actual) | Nuevo status |
|---|---|
| **TechnicalWriterAgent** | → Consolidado en GenerationFactory |
| **FormatsAgent** | → Consolidado en GenerationFactory |
| **EconomicWriterAgent** | → Consolidado en GenerationFactory |
| **DocumentPackagerAgent** | → Consolidado en GenerationFactory |
| **DeliveryAgent** | → Consolidado en GenerationFactory |

### Fuera del pipeline
| Agente | Dominio |
|---|---|
| **ChatbotRAGAgent** | Consultas de usuario (reactivo, no decisional) |

---

## 2. Arquitectura Objetivo

```
ORQUESTADOR (L1 — Decisional)
  │
  ├── ANALYST │ COMPLIANCE │ ECONOMIC │ INTAKE (L2)
  │
  ├── DATAGAP (L2)
  │
  ├── FORENSIC_AUDITOR (L2 — ver sección 3)
  │     └── Poder de VETO obligatorio sobre Orchestrator
  │
  └── GENERATION_FACTORY (L3 — ver sección 4)
        └── No hereda BaseAgent — es un TaskRunner/Service

CHATBOT_RAG (fuera del pipeline — consultas de usuario)
```

---

## 3. ForensicAuditor — Especificación Completa

### 3.1 Propósito
Agente unificado que reemplaza ValidatorAgent + CriticAgent.
Evalúa calidad de resultados y tiene veto efectivo obligatorio sobre el Orchestrator.

### 3.2 Contrato de salida (schema Pydantic)

```python
class ForensicAuditorOutput(BaseModel):
    model_config = {"extra": "forbid"}

    verdict: Literal["continue", "rerun_analyst", "rerun_compliance", "escalate"]
    veto_triggered: bool  # True si verdict != "continue"
    evaluation_details: Dict[str, Any]  # Quién evaluó qué (traceability)
    verdict_reason: str  # Explicación legible para auditoría
    suggested_corrections: Dict[str, List[str]]  # req_id → lista de hints
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)

    # Traceability: quién hizo qué dentro del agente unificado
    validator_part: Optional[Dict[str, Any]] = None  # Resultado de evaluación técnica
    critic_part: Optional[Dict[str, Any]] = None     # Resultado de decisión
```

### 3.3 Regla de Veto (NO configurable)

```python
# En Orchestrator.process — guarda obligatoria:
async def process(self, session_id: str, input_data: Dict) -> Dict:
    # ... análisis y compliance ...

    # Evaluación forense obligatoria
    forensic_report = await ForensicAuditor(self.context_manager).evaluate(
        analysis_result=execution_results.get("analysis"),
        compliance_result=execution_results.get("compliance")
    )

    # GRABAR en tasks_completed antes de cualquier decisión
    await self.context_manager.record_task_completion(
        session_id=session_id,
        task_name="forensic_audit",
        result=forensic_report.model_dump()
    )

    # VETO OBLIGATORIO — no puede ser ignorado por configuración
    if forensic_report.veto_triggered:
        logger.warning(
            "[FORENSIC_AUDITOR] Veto activado: %s | razón: %s",
            forensic_report.verdict,
            forensic_report.verdict_reason
        )
        return await self._execute_backtrack(
            hints=forensic_report.suggested_corrections,
            verdict=forensic_report.verdict,
            iteration=bt_iterations
        )

    # Solo continúa si veto no está activado
```

### 3.4 Límites de reintento (deadlock prevention)

```python
# Configurado en settings (no en código — modificable por ops)
BACKTRACK_MAX_ITERATIONS: int = 3  # default

# En Orchestrator:
if bt_iterations >= settings.BACKTRACK_MAX_ITERATIONS:
    # Escalar a revisión humana — no reintentar más
    decision = OrchestratorState(
        stop_reason="ESCALATE_TO_HUMAN",
        aggregate_health="failed",
        next_steps=next_steps,
        verdict_reason=forensic_report.verdict_reason
    )
    return {"status": "escalated", ...}
```

### 3.5 Traceability (no negociable)

- Cada evaluación graba `validator_part` y `critic_part` en la salida
- `verdict_reason` es un string legible para auditoría humana
- `evaluation_details` persiste en `tasks_completed` — no se pierde entre ejecuciones

---

## 4. GenerationFactory — Especificación

### 4.1 Propósito
Reemplazar 5 agentes independientes (TechnicalWriter, Formats, EconomicWriter, DocumentPackager, Delivery) con un servicio unificado.

### 4.2 Ubicación

```
backend/app/services/
├── generation_factory.py   ← El servicio único
└── templates/              ← Plantillas Jinja2 compartidas
    ├── technical_document.j2
    ├── formato_licitacion.j2
    ├── economic_report.j2
    └── ...
```

### 4.3 Interfaz

```python
class GenerationFactory:
    """
    Servicio unificado de generación de documentos.
    No hereda de BaseAgent — es un TaskRunner simple.
    """

    def __init__(self, template_dir: Path = None):
        self.template_dir = template_dir or Path(__file__).parent / "templates"

    async def generate(
        self,
        session_id: str,
        compliance_data: Dict[str, Any],
        economic_data: Optional[Dict[str, Any]] = None,
        output_format: Literal["pdf", "docx", "html"] = "pdf"
    ) -> GenerationResult:
        # 1) Renderizar technical document
        # 2) Aplicar formatos de plantilla
        # 3) Integrar análisis económico
        # 4) Ensamblar paquete final
        # 5) Entregar
```

### 4.4 Por qué NO hereda de BaseAgent

- BaseAgent implica messaging via Redis, heredando overhead de MCP
- GenerationFactory es un pipeline secuencial determinístico
- Compartir plantillas Jinja2 y buffers de memoria es más eficiente en un solo proceso
- Más fácil de debuggear — un solo punto de entrada

---

## 5. Plan de Implementación (Rollout Gradual)

### Fase 0 — Feature Flags (antes de tocar código)

```python
# En backend/app/config/settings.py
FORENSIC_AUDITOR_ENABLED: bool = False  # Default: legacy (Validator + Critic)
GENERATION_FACTORY_ENABLED: bool = False  # Default: legacy agents
```

### Fase 1 — ForensicAuditor (sin eliminar lo existente)

1. Crear `backend/app/agents/forensic_auditor.py` con el contrato de la sección 3.2
2. Mantener ValidatorAgent y CriticAgent funcionando (no tocar)
3. Agregar feature flag `FORENSIC_AUDITOR_ENABLED`
4. En Orchestrator: si flag=True, usar ForensicAuditor; si False, usar Validator+Critic
5. Correr tests de regresión con ambos paths

**Checkpoint de validación:**
```bash
# Ambos paths deben dar resultados equivalentes en casos de prueba
pytest backend/tests/test_forensic_auditor_equivalence.py -v
```

### Fase 2 — GenerationFactory (sin eliminar lo existente)

1. Crear `backend/app/services/generation_factory.py`
2. Mantener los 5 agentes de generación funcionando
3. Agregar feature flag `GENERATION_FACTORY_ENABLED`
4. En Orchestrator: si flag=True, usar factory; si False, usar agentes individuales
5. Correr tests de regresión

**Checkpoint de validación:**
```bash
# El output de factory debe ser idéntico al de los 5 agentes separados
pytest backend/tests/test_generation_factory_equivalence.py -v
```

### Fase 3 — Cleanup (solo cuando Fase 1 y 2 validadas)

1. Eliminar ValidatorAgent y CriticAgent (o deprecar)
2. Eliminar los 5 agentes de generación (o deprecar)
3. Poner feature flags en True por default
4. Eliminar código legacy

---

## 6. Checklist de Validación por Fase

### Fase 1 — ForensicAuditor

- [ ] ForensicAuditorOutput schema creado y validado
- [ ] Evaluaciones graban `validator_part` y `critic_part`
- [ ] Veto es guarda obligatoria (no skipeable por config)
- [ ] Límite de reintentos funciona (`BACKTRACK_MAX_ITERATIONS`)
- [ ] Traceability persiste en `tasks_completed`
- [ ] Tests de equivalencia pasan (ambos paths = mismo resultado)
- [ ] Timeout de agents/process no se degrada

### Fase 2 — GenerationFactory

- [ ] Factory genera documentos idénticos a la suma de los 5 agentes
- [ ] Plantillas Jinja2 compartidas y versionadas
- [ ] Memoria y latencia mejoran vs. 5 agentes separados
- [ ] Tests de equivalencia pasan
- [ ] PDF/DOCX output verificable byte-a-byte equivalente

### Fase 3 — Cleanup

- [ ] Feature flags removidos (o dejados como deprecated)
- [ ] Código legacy eliminado o marcado como deprecated
- [ ] AGENTS_CONTEXT.md actualizado con nueva arquitectura
- [ ] Documentación de onboarding actualizada

---

## 7. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| ForensicAuditor introduce deadlock (veta siempre) | Baja | Alta | `BACKTRACK_MAX_ITERATIONS` + escala a humano |
| Se pierde traceability al fusionar Validator+Critic | Media | Alta | Contrato con `validator_part` + `critic_part` explícitos |
| GenerationFactory genera output diferente a los 5 agentes | Media | Media | Tests de equivalencia antes de switch |
| Backward compatibility se rompe | Baja | Alta | Feature flags permiten rollback sin deploy |
| El Orchestrator no respeta veto | — | Crítica | Veto es guarda en código, no flag |

---

## 8. Referencias

- Contrato ForensicAuditorOutput: `backend/app/contracts/forensic_auditor_contracts.py` (por crear)
- Contrato OrchestratorState: `backend/app/contracts/orchestrator_contracts.py`
- SessionStateV1: `backend/app/contracts/session_contracts.py`
- Feature flags existentes: `backend/app/config/settings.py`
- Tests de equivalencia: `backend/tests/test_forensic_auditor_equivalence.py` (por crear), `backend/tests/test_generation_factory_equivalence.py` (por crear)

---

## 9. Metadata del Documento

| Campo | Valor |
|---|---|
| Autores | Claude + Antigravity + Cursor |
| Basado en | Discusión tripartita 2026-03-31 |
| Versión documento | 1.0 |
| Estado | PENDIENTE — por implementar |
| Prioridad | Alta — habilita escalabilidad del sistema |
