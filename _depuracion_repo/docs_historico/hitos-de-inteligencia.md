# Hitos de Inteligencia para LicitAI

## Roadmap hacia un Sistema Multi-Agente Realmente Inteligente

Este documento define 7 hitos de implementación para transformar LicitAI de un pipeline de procesamiento secuencial a un sistema inteligente con capacidades de aprendizaje, razonamiento y adaptación.

---

## HITO 1: Memoria de Experiencia (Learning System)

### Objetivo
El sistema debe aprender de licitaciones anteriores, identificando patrones de éxito/fracaso y aplicando ese conocimiento a nuevas licitaciones.

### Componentes a Construir

#### 1.1 Experience Vector Store
**Ubicación:** `backend/app/memory/experience_store.py`

**Estructura de datos:**
```python
@dataclass
class LicitacionExperience:
    id: str
    sector: str  # salud, construcción, tecnología, etc.
    tipo_licitacion: str  # obra pública, servicios, adquisiciones
    requisitos_extraidos: List[Dict]  # Normalizados
    estrategia_usada: Dict  # Qué documentos se generaron, precios propuestos
    resultado: str  # "won", "lost", "disqualified", "abandoned"
    factores_exito: List[str]  # Identificados post-hoc
    factores_fracaso: List[str]
    fecha: datetime
    empresa_id: str
```

**Funcionalidades requeridas:**
- `store_experience(licitacion: LicitacionExperience) → bool`
- `find_similar_cases(sector, tipo, requisitos, top_k=5) → List[LicitacionExperience]`
- `get_success_patterns(sector, tipo) → Dict[str, float]`  # Qué estrategias funcionan
- `get_common_pitfalls(sector) → List[str]`  # Errores frecuentes

#### 1.2 Experience-Augmented Prompts
**Ubicación:** Modificar `backend/app/agents/analyst.py` y `compliance.py`

**Comportamiento:**
Antes de procesar una nueva licitación, el sistema debe:
1. Buscar casos similares en el Experience Store
2. Inyectar insights relevantes en los system prompts

**Ejemplo de prompt enriquecido:**
```python
system_prompt = f"""
Eres un experto ANALISTA FORENSE de licitaciones del sector {sector}.

CONTEXTO DE EXPERIENCIA PREVIA:
- Casos similares procesados: {len(similar_cases)}
- Patrón de éxito identificado: {success_patterns}
- Advertencias de casos pasados: {common_pitfalls}

REGLAS DE ORO:
...
"""
```

#### 1.3 Feedback Loop para Aprendizaje
**Nuevas tablas en PostgreSQL:**
```sql
CREATE TABLE licitacion_outcomes (
    id UUID PRIMARY KEY,
    session_id VARCHAR REFERENCES sessions(id),
    sector VARCHAR,
    tipo VARCHAR,
    resultado VARCHAR CHECK (resultado IN ('won', 'lost', 'disqualified', 'abandoned', 'pending')),
    factores_exito JSON,
    factores_fracaso JSON,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE requirement_patterns (
    id UUID PRIMARY KEY,
    sector VARCHAR,
    requirement_hash VARCHAR,  # Hash del texto normalizado
    interpretacion_comun JSON,  # Cómo se interpretó en casos pasados
    tasa_exito FLOAT,  # % de éxito cuando se interpretó así
    frecuencia INT  # Cuántas veces apareció
);
```

### Criterios de Aceptación (Tests)

1. **Test de Almacenamiento:**
   ```python
   async def test_experience_storage():
       exp = create_mock_licitacion_experience(sector="salud", resultado="won")
       await experience_store.store_experience(exp)
       retrieved = await experience_store.get_by_id(exp.id)
       assert retrieved.resultado == "won"
   ```

2. **Test de Recuperación Similar:**
   ```python
   async def test_similar_case_retrieval():
       # Crear 10 casos de salud, 5 ganados, 5 perdidos
       await seed_test_experiences("salud", 10)

       # Buscar similares a nuevo caso
       similar = await experience_store.find_similar_cases(
           sector="salud",
           tipo="servicios",
           requisitos=["RFC", "Constancia de situación fiscal"]
       )
       assert len(similar) == 5
       assert all(s.sector == "salud" for s in similar)
   ```

3. **Test de Enriquecimiento de Prompts:**
   ```python
   async def test_prompt_enrichment():
       analyst = AnalystAgent(context_manager, use_experience=True)
       result = await analyst.process(session_id, input_data)

       # Verificar que el prompt incluyó contexto de experiencia
       assert "Casos similares" in analyst._last_system_prompt
   ```

4. **Test E2E de Aprendizaje:**
   ```python
   async def test_learning_over_time():
       # Procesar primera licitación
       result1 = await process_licitacion(mock_licitacion_1)
       await report_outcome(result1.session_id, "won")

       # Procesar segunda similar
       result2 = await process_licitacion(mock_licitacion_2)  # Similar a 1

       # Verificar que se aplicaron aprendizajes del caso 1
       assert result2.metadata["experience_applied"] == True
   ```

---

## HITO 2: Razonamiento Multi-Paso y Auto-Corrección

### Objetivo
Implementar ciclos de refinamiento donde los agentes pueden discutir entre sí, detectar inconsistencias y retroceder para corregir.

### Componentes a Construir

#### 2.1 Agent Communication Bus
**Ubicación:** `backend/app/agents/communication/bus.py`

**Concepto:** Pub/Sub interno para que agentes se comuniquen.

```python
class AgentCommunicationBus:
    def __init__(self):
        self.channels: Dict[str, List[Callable]] = {}

    async def publish(self, channel: str, message: AgentMessage):
        for handler in self.channels.get(channel, []):
            await handler(message)

    def subscribe(self, channel: str, handler: Callable):
        self.channels.setdefault(channel, []).append(handler)

@dataclass
class AgentMessage:
    from_agent: str
    to_agent: Optional[str]  # None = broadcast
    message_type: str  # "challenge", "question", "correction", "confirm"
    payload: Dict
    timestamp: datetime
```

#### 2.2 ValidatorAgent
**Ubicación:** `backend/app/agents/validator.py`

**Nuevo agente** que actúa como árbitro entre Analyst y Compliance.

```python
class ValidatorAgent(BaseAgent):
    """
    Agente de Validación Cruzada.
    Verifica consistencia entre extracciones de diferentes agentes.
    """

    async def validate_consistency(
        self,
        session_id: str,
        analyst_result: Dict,
        compliance_result: Dict
    ) -> ValidationReport:
        """
        Retorna:
        - consistent: bool
        - conflicts: List[Conflict]
        - resolution_strategy: str
        """
```

**Tipos de validación:**
1. **Cobertura:** ¿El Compliance cubrió todos los requisitos que el Analyst encontró?
2. **Contradicción:** ¿Hay requisitos que Analyst dice son "filtro" pero Compliance ignora?
3. **Duplicación:** ¿Hay requisitos duplicados con diferentes IDs?

#### 2.3 Backtracking en Orchestrator
**Modificar:** `backend/app/agents/orchestrator.py`

**Nueva lógica de orquestación con ciclos:**

```python
class OrchestratorAgent:
    async def process_with_refinement(self, session_id, input_data, max_iterations=3):
        for iteration in range(max_iterations):
            # Ejecutar pipeline
            analyst_result = await self.run_analyst(session_id, input_data)
            compliance_result = await self.run_compliance(session_id, input_data)

            # Validar
            validation = await self.validator.validate(
                analyst_result, compliance_result
            )

            if validation.consistent:
                break  # Éxito

            # Backtracking inteligente
            if validation.requires_analyst_revision:
                input_data["corrections"] = validation.suggested_corrections
                continue  # Re-ejecutar desde Analyst

            if validation.requires_compliance_revision:
                input_data["focus_areas"] = validation.missing_areas
                continue  # Re-ejecutar Compliance

        return final_result
```

#### 2.4 Arbitration System
**Ubicación:** `backend/app/agents/arbitration.py`

Cuando hay conflictos irreconciliables entre agentes, un sistema de arbitraje decide.

```python
class ArbitrationEngine:
    async def resolve_conflict(
        self,
        conflict: Conflict,
        context: Dict
    ) -> Resolution:
        """
        Estrategias de resolución:
        1. Mayor confianza: El agente con score más alto gana
        2. Consenso: LLM de arbitraje decide basado en evidencia
        3. Humano: Escalar al usuario
        """
```

### Criterios de Aceptación (Tests)

1. **Test de Detección de Inconsistencias:**
   ```python
   async def test_inconsistency_detection():
       analyst_result = {"requisitos": ["A", "B", "C"]}
       compliance_result = {"requisitos": ["A", "B"]}  # Falta C

       validation = await validator.validate(analyst_result, compliance_result)
       assert validation.consistent == False
       assert any(c.type == "missing_coverage" for c in validation.conflicts)
   ```

2. **Test de Backtracking:**
   ```python
   async def test_orchestrator_backtracking():
       # Simular caso donde Compliance falla inicialmente
       with mock.patch('ComplianceAgent.process') as mock_compliance:
           mock_compliance.side_effect = [
               {"status": "partial", "data": {}},  # Primera falla
               {"status": "success", "data": {...}}  # Segundo intento OK
           ]

           result = await orchestrator.process_with_refinement(session_id, data)
           assert result["iterations"] == 2
           assert result["final_status"] == "success"
   ```

3. **Test de Comunicación entre Agentes:**
   ```python
   async def test_agent_communication():
       bus = AgentCommunicationBus()

       messages_received = []
       bus.subscribe("compliance", lambda m: messages_received.append(m))

       await bus.publish("compliance", AgentMessage(
           from_agent="analyst",
           message_type="challenge",
           payload={"issue": "missed_requirement", "req_id": "REQ-05"}
       ))

       assert len(messages_received) == 1
   ```

4. **Test E2E de Corrección en Cascada:**
   ```python
   async def test_cascading_correction():
       # Procesar licitación con datos intencionalmente contradictorios
       result = await process_licitacion(contradictory_mock)

       # Verificar que se detectaron y corrigieron las contradicciones
       assert result["refinements_applied"] > 0
       assert result["consistency_score"] > 0.9
   ```

---

## HITO 3: Evaluación de Confianza (Uncertainty Quantification)

### Objetivo
Cada extracción debe incluir una métrica de confianza. El sistema debe saber cuándo NO sabe.

### Componentes a Construir

#### 3.1 Confidence Scorer
**Ubicación:** `backend/app/services/confidence_scorer.py`

```python
class ConfidenceScorer:
    """
    Calcula confianza de extracciones basado en múltiples señales.
    """

    def calculate_extraction_confidence(
        self,
        extracted_text: str,
        source_context: str,
        llm_raw_output: str,
        extraction_method: str
    ) -> ConfidenceScore:
        """
        Señales de confianza:
        1. Evidencia literal: ¿El texto extraído aparece exactamente en la fuente?
        2. Consistencia RAG: ¿Múltiples chunks dicen lo mismo?
        3. Claridad LLM: ¿El LLM expresó duda ("probablemente", "quizás")?
        4. Longitud contexto: ¿Tenía suficiente contexto?
        5. Historial: ¿Este tipo de extracción suele ser correcto?
        """

@dataclass
class ConfidenceScore:
    overall: float  # 0.0 - 1.0
    breakdown: Dict[str, float]  # Desglose por señal
    threshold_passed: bool  # ¿Supera el umbral mínimo?
    recommendation: str  # "accept", "review", "reject", "escalate"
```

#### 3.2 Uncertainty-Aware Agents
**Modificar:** Todos los agentes deben retornar scores de confianza.

```python
# Nuevo contrato de retorno
class AgentResult:
    data: Dict
    confidence: ConfidenceScore
    alternative_interpretations: List[str]  # "Otras formas de interpretar esto"
    unknowns: List[str]  # Qué se identificó como ambiguo
```

**Ejemplo en AnalystAgent:**
```python
async def process(self, session_id, input_data):
    # Extracción actual
    raw_extraction = await self.llm.generate(...)

    # Calcular confianza
    confidence = self.confidence_scorer.calculate(
        extracted=raw_extraction,
        source=source_context,
        method="llm_extraction"
    )

    # Si confianza baja, intentar estrategias alternativas
    if confidence.overall < 0.7:
        # Estrategia 1: Re-preguntar con prompt diferente
        # Estrategia 2: Buscar contexto adicional
        # Estrategia 3: Marcar para revisión humana
        alternative = await self.retry_with_context_expansion(...)
    ```

#### 3.3 Consensus Mechanism
**Ubicación:** `backend/app/services/consensus.py`

Para requisitos críticos, usar múltiples estrategias de extracción y votar.

```python
class ConsensusExtractor:
    async def extract_with_consensus(
        self,
        session_id: str,
        query: str,
        strategies: List[str] = ["direct", "context_expanded", "section_based"]
    ) -> ConsensusResult:
        """
        Ejecuta múltiples extracciones y determina consenso.
        """
        results = []
        for strategy in strategies:
            result = await self.extract_with_strategy(strategy)
            results.append(result)

        # Si 2/3 coinciden, confianza alta
        # Si discrepan, confianza baja + escalación
```

#### 3.4 Confidence-Based Routing
**Modificar:** `OrchestratorAgent`

```python
async def route_based_on_confidence(self, results):
    low_confidence_items = [
        r for r in results
        if r.confidence.overall < CONFIDENCE_THRESHOLD
    ]

    if len(low_confidence_items) > MAX_LOW_CONFIDENCE:
        # Estrategia: Escalar a humano
        return await self.escalate_for_review(low_confidence_items)

    if len(low_confidence_items) > 0:
        # Estrategia: Re-ejecutar con más contexto
        return await self.retry_with_expanded_context(low_confidence_items)
```

### Criterios de Aceptación (Tests)

1. **Test de Señales de Confianza:**
   ```python
   async def test_confidence_signals():
       # Texto que existe exactamente en la fuente → Alta confianza
       exact_match = "El plazo es de 30 días naturales"
       score1 = scorer.calculate(exact_match, source_with_text)
       assert score1.overall > 0.9

       # Texto interpretado/no literal → Baja confianza
       interpreted = "Probablemente se requieren 30 días"
       score2 = scorer.calculate(interpreted, source_without_text)
       assert score2.overall < 0.6
   ```

2. **Test de Routing por Confianza:**
   ```python
   async def test_confidence_routing():
       # Simular resultados con baja confianza
       low_conf_results = [mock_result(confidence=0.5) for _ in range(10)]

       decision = await orchestrator.route_based_on_confidence(low_conf_results)
       assert decision.action == "escalate"
   ```

3. **Test de Consenso:**
   ```python
   async def test_consensus_extraction():
       # Crear documento con requisito claro
       consensus = await consensus_extractor.extract(
           query="plazo de entrega",
           strategies=["direct", "rag", "section"]
       )

       # Debe haber acuerdo entre estrategias
       assert consensus.agreement_rate > 0.8
       assert consensus.final_confidence > 0.85
   ```

4. **Test E2E de Detección de Incertidumbre:**
   ```python
   async def test_uncertainty_detection():
       # Procesar documento ambiguo intencionalmente
       result = await process_licitacion(ambiguous_mock)

       # Debe identificar qué no está claro
       assert len(result["uncertainties"]) > 0
       assert any(u["escalated"] for u in result["uncertainties"])
   ```

---

## HITO 4: Integración con Inteligencia de Mercado

### Objetivo
El sistema debe tener visibilidad de precios de mercado, competidores y benchmarks históricos.

### Componentes a Construir

#### 4.1 Market Intelligence Service
**Ubicación:** `backend/app/services/market_intelligence.py`

```python
class MarketIntelligenceService:
    """
    Agregador de datos de mercado para benchmarking.
    """

    async def get_price_benchmark(
        self,
        item: str,
        unit: str,
        sector: str,
        region: Optional[str] = None
    ) -> PriceBenchmark:
        """
        Retorna:
        - market_low: Precio más bajo encontrado
        - market_high: Precio más alto
        - market_avg: Promedio
        - recommended_range: Rango "competitivo"
        - data_points: Cuántos registros alimentan el benchmark
        """

    async def get_competitor_analysis(
        self,
        sector: str,
        time_range: str = "1y"
    ) -> CompetitorAnalysis:
        """
        Análisis de licitaciones ganadas en el sector.
        """
```

#### 4.2 Conectores a Fuentes Externas
**Ubicación:** `backend/app/integrations/`

**Implementar conectores para:**

1. **Compranet (México)** - `compranet_client.py`
2. **SECOPII (Colombia)** - `secop_client.py`
3. **TED EU (Unión Europea)** - `ted_client.py`
4. **Mercado Público (Chile)** - `mercado_publico_client.py`

**Interfaz común:**
```python
class GovernmentProcurementClient(ABC):
    @abstractmethod
    async def search_awarded_contracts(
        self,
        keywords: List[str],
        date_from: datetime,
        date_to: datetime
    ) -> List[AwardedContract]:
        pass
```

#### 4.3 Price Alert System
**Ubicación:** `backend/app/services/price_alerts.py`

```python
class PriceAlertService:
    async def validate_company_prices(
        self,
        company_catalog: List[CatalogItem],
        sector: str
    ) -> PriceValidationReport:
        """
        Compara precios de la empresa contra mercado y genera alertas:
        - WARNING: Precio 20% superior al promedio
        - CRITICAL: Precio 40% superior (poco competitivo)
        - OPPORTUNITY: Precio 30% inferior (margen para subir)
        """
```

#### 4.4 Competitor Tracking
**Nueva tabla PostgreSQL:**
```sql
CREATE TABLE competitor_prices (
    id UUID PRIMARY KEY,
    licitacion_id VARCHAR,
    empresa_ganadora VARCHAR,
    sector VARCHAR,
    item_descripcion TEXT,
    precio_unitario DECIMAL,
    moneda VARCHAR,
    fecha_licitacion TIMESTAMP,
    fuente VARCHAR  # De dónde viene el dato
);

CREATE INDEX idx_competitor_sector ON competitor_prices(sector);
CREATE INDEX idx_competitor_item ON competitor_prices USING gin(item_descripcion gin_trgm_ops);
```

### Criterios de Aceptación (Tests)

1. **Test de Benchmark de Precios:**
   ```python
   async def test_price_benchmark():
       # Seed con datos de mercado simulados
       await seed_competitor_prices([
           {"item": "Limpieza m2", "precio": 15.50},
           {"item": "Limpieza m2", "precio": 18.00},
           {"item": "Limpieza m2", "precio": 22.00},
       ])

       benchmark = await market_intel.get_price_benchmark(
           item="Limpieza",
           unit="m2",
           sector="servicios"
       )

       assert benchmark.market_avg == 18.50
       assert benchmark.data_points == 3
   ```

2. **Test de Alertas de Precio:**
   ```python
   async def test_price_alerts():
       company_catalog = [{"item": "Limpieza", "price": 35.00}]  # Muy alto

       alerts = await price_alert_service.validate_company_prices(
           company_catalog, sector="servicios"
       )

       assert any(a.level == "CRITICAL" for a in alerts)
   ```

3. **Test de Conector Compranet:**
   ```python
   async def test_compranet_client():
       # Usar mocks para no depender de API externa
       with aioresponses() as mocked:
           mocked.get(
               "https://api.compranet.gob.mx/...",
               payload={"contracts": [...]}
           )

           contracts = await compranet_client.search_awarded_contracts(
               keywords=["limpieza"],
               date_from=datetime(2024, 1, 1)
           )

           assert len(contracts) > 0
   ```

4. **Test E2E de Integración Económica:**
   ```python
   async def test_economic_with_market_data():
       result = await process_licitacion(
           mock_licitacion,
           enable_market_intelligence=True
       )

       # Debe incluir comparación de mercado
       assert "market_comparison" in result["economic"]
       assert "competitiveness_score" in result["economic"]
   ```

---

## HITO 5: Sistema de Feedback y Mejora Continua

### Objetivo
Mecanismo para que usuarios corrijan errores y el sistema aprenda de esas correcciones.

### Componentes a Construir

#### 5.1 Feedback Capture UI
**Frontend:** Modificar `frontend/src/components/ResultsReview.jsx`

**Funcionalidad:**
- Checkbox "¿Esta extracción es correcta?" en cada requisito
- Modal de corrección: "¿Cuál es el valor correcto?"
- Botón "Reportar error grave" para casos críticos
- Feedback por categoría: "Análisis", "Compliance", "Económico"

#### 5.2 Feedback Storage
**Nuevas tablas:**
```sql
CREATE TABLE extraction_feedback (
    id UUID PRIMARY KEY,
    session_id VARCHAR,
    agent_id VARCHAR,
    field_name VARCHAR,
    extracted_value TEXT,
    user_correction TEXT,
    was_correct BOOLEAN,
    correction_type VARCHAR,  -- "value_error", "missing", "false_positive"
    user_comment TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE prompt_performance (
    id UUID PRIMARY KEY,
    prompt_version VARCHAR,
    agent_id VARCHAR,
    extractions_count INT,
    correct_count INT,
    accuracy_rate FLOAT,
    avg_confidence FLOAT
);
```

#### 5.3 RLHF (Reinforcement Learning from Human Feedback)
**Ubicación:** `backend/app/learning/rlhf.py`

```python
class RLHFTrainer:
    """
    Ajusta prompts y parámetros basado en feedback de usuarios.
    """

    async def analyze_feedback_trends(
        self,
        agent_id: str,
        time_window: str = "30d"
    ) -> FeedbackAnalysis:
        """
        Identifica:
        - Campos que más errores generan
        - Tipos de error comunes
        - Prompts que necesitan ajuste
        """

    async def suggest_prompt_improvement(
        self,
        agent_id: str,
        feedback_data: List[FeedbackEntry]
    ) -> PromptSuggestion:
        """
        Usa LLM para sugerir mejoras al prompt basado en errores.
        """

    async def apply_prompt_variant(
        self,
        agent_id: str,
        new_prompt: str,
        rollout_percentage: float = 10.0
    ):
        """
        A/B testing: Aplica nuevo prompt a % de sesiones y mide mejora.
        """
```

#### 5.4 Human-in-the-Loop Triggers
**Modificar:** `OrchestratorAgent`

```python
async def should_escalate_to_human(
    self,
    confidence_scores: List[ConfidenceScore],
    critical_requirements: List[str]
) -> EscalationDecision:
    """
    Escalar si:
    1. Confianza promedio < 0.6
    2. Requisitos críticos tienen confianza baja
    3. Hay conflictos no resueltos entre agentes
    4. El usuario ha marcado este tipo de licitación como "compleja" previamente
    """
```

### Criterios de Aceptación (Tests)

1. **Test de Almacenamiento de Feedback:**
   ```python
   async def test_feedback_storage():
       feedback = ExtractionFeedback(
           session_id="sess-001",
           agent_id="compliance_001",
           field_name="garantia_seriedad",
           extracted_value="5%",
           user_correction="3%",
           was_correct=False
       )

       await feedback_repo.save(feedback)
       retrieved = await feedback_repo.get_by_session("sess-001")
       assert retrieved.user_correction == "3%"
   ```

2. **Test de Análisis de Tendencias:**
   ```python
   async def test_feedback_trend_analysis():
       # Seed con feedback histórico
       await seed_feedback([
           {"agent": "analyst", "was_correct": False, "field": "fecha_fallo"},
           {"agent": "analyst", "was_correct": False, "field": "fecha_fallo"},
           {"agent": "analyst", "was_correct": True, "field": "garantia"},
       ])

       analysis = await rlhf.analyze_feedback_trends("analyst")

       # Debe identificar que "fecha_fallo" es problemático
       assert "fecha_fallo" in analysis.problematic_fields
   ```

3. **Test de Escalamiento Humano:**
   ```python
   async def test_human_escalation():
       low_conf_results = [mock_result(confidence=0.5) for _ in range(5)]

       decision = await orchestrator.should_escalate_to_human(
           low_conf_results,
           critical_requirements=["garantia_cumplimiento"]
       )

       assert decision.should_escalate == True
       assert decision.reason == "LOW_CONFIDENCE_CRITICAL_FIELDS"
   ```

4. **Test E2E de Ciclo de Feedback:**
   ```python
   async def test_feedback_cycle():
       # 1. Procesar licitación
       result = await process_licitacion(mock_licitacion)

       # 2. Simular corrección de usuario
       await submit_feedback(
           session_id=result.session_id,
           field="criterio_evaluacion",
           correction="Puntos y Porcentajes (no Costo Menor como se extrajo)"
       )

       # 3. Verificar que el feedback está almacenado
       feedback = await get_feedback(result.session_id)
       assert len(feedback) == 1

       # 4. Verificar que el análisis de RLHF lo detecta
       trends = await rlhf.analyze_feedback_trends("analyst")
       assert "criterio_evaluacion" in trends.fields_with_corrections
   ```

---

## HITO 6: Orquestador Inteligente/Adaptativo

### Objetivo
El Orchestrator debe adaptar el pipeline dinámicamente según el contexto de cada licitación.

### Componentes a Construir

#### 6.1 Pipeline Configurator
**Ubicación:** `backend/app/orchestration/pipeline_configurator.py`

```python
class PipelineConfigurator:
    """
    Determina qué agentes ejecutar y en qué orden según características de la licitación.
    """

    async def configure_pipeline(
        self,
        document_metadata: DocumentMetadata,
        company_profile: Dict
    ) -> PipelineConfig:
        """
        Decisiones de configuración:
        - ¿Documento corto? Simplificar Compliance (sin Map-Reduce)
        - ¿Tipo de evaluación = COSTO MENOR? Priorizar Economic sobre Technical
        - ¿Empresa nueva? Añadir onboarding flow
        - ¿Sector de alto riesgo? Añadir validator extra
        """

@dataclass
class PipelineConfig:
    stages: List[PipelineStage]
    short_circuit_conditions: List[ShortCircuitRule]
    retry_policy: RetryPolicy
    parallelization_groups: List[List[str]]  # Qué agentes pueden correr en paralelo
```

#### 6.2 Dynamic Stage Injection
**Modificar:** `OrchestratorAgent`

```python
class AdaptiveOrchestrator:
    async def execute_adaptive_pipeline(self, session_id, input_data):
        # 1. Analizar documento para configuración
        doc_profile = await self.profile_document(input_data)

        # 2. Obtener configuración dinámica
        config = await self.configurator.configure_pipeline(
            doc_profile,
            input_data["company_profile"]
        )

        # 3. Ejecutar pipeline adaptado
        for stage in config.stages:
            if await self.should_skip_stage(stage, session_state):
                continue

            result = await self.execute_stage(stage)

            # Decisión dinámica: ¿continuar o abortar?
            if not await self.should_continue(result, config.short_circuit_conditions):
                break
```

#### 6.3 Short-Circuit Rules
```python
@dataclass
class ShortCircuitRule:
    condition: str  # Python expression evaluable
    action: str  # "stop", "retry", "escalate", "skip_to_stage"
    target: Optional[str]  # Si action es skip_to_stage, a qué stage ir

# Ejemplos:
RULES = [
    ShortCircuitRule(
        condition="compliance.items_count < 5",
        action="retry",
        target=None  # Re-ejecutar compliance con más contexto
    ),
    ShortCircuitRule(
        condition="data_gap.critical_missing > 10",
        action="stop",
        target="intake_mode"  # Cambiar a modo recolección de datos
    ),
]
```

#### 6.4 Checkpoint y Reanudación Mejorada
**Modificar:** `OrchestratorAgent`

```python
class CheckpointManager:
    async def create_checkpoint(
        self,
        session_id: str,
        stage: str,
        state: Dict
    ):
        """
        Guarda estado completo para poder reanudar desde cualquier punto.
        """

    async def resume_from_checkpoint(
        self,
        session_id: str,
        checkpoint_id: Optional[str] = None  # None = último
    ) -> ResumeState:
        """
        Reanuda ejecución desde un checkpoint.
        Permite:
        - Retomar después de error
        - Re-ejecutar desde punto intermedio con datos modificados
        - Comparar resultados de diferentes estrategias
        """
```

### Criterios de Aceptación (Tests)

1. **Test de Configuración Dinámica:**
   ```python
   async def test_dynamic_pipeline_config():
       # Documento corto (10 páginas)
       short_doc = mock_document(pages=10, type="simple")
       config = await configurator.configure_pipeline(short_doc, {})

       # Debe usar pipeline simplificado
       assert config.stages[2].agent == "compliance_light"  # Sin Map-Reduce

       # Documento largo complejo
       long_doc = mock_document(pages=200, type="complex")
       config2 = await configurator.configure_pipeline(long_doc, {})

       assert config2.stages[2].agent == "compliance_full"  # Con Map-Reduce
   ```

2. **Test de Short-Circuit:**
   ```python
   async def test_short_circuit_rules():
       rule = ShortCircuitRule(
           condition="compliance.items_count < 5",
           action="retry"
       )

       # Simular resultado que dispara la regla
       result = {"compliance": {"items_count": 3}}

       should_retry = evaluate_rule(rule, result)
       assert should_retry == True
   ```

3. **Test de Checkpoint:**
   ```python
   async def test_checkpoint_resume():
       # Crear checkpoint en medio del pipeline
       checkpoint = await checkpoint_manager.create_checkpoint(
           session_id="sess-001",
           stage="compliance",
           state={"partial_results": [...]}
       )

       # Simular crash y reanudar
       resumed = await orchestrator.resume_from_checkpoint(
           "sess-001",
           checkpoint.id
       )

       assert resumed.current_stage == "compliance"
       assert resumed.state["partial_results"] == checkpoint.state["partial_results"]
   ```

4. **Test E2E de Adaptación:**
   ```python
   async def test_adaptive_pipeline_e2e():
       # Procesar licitación tipo COSTO MENOR
       result = await process_licitacion(
           mock_costo_menor_licitacion,
           adaptive_mode=True
       )

       # Debe haber priorizado agente económico
       assert result["execution_log"]["stages"][2]["agent"] == "economic"
       assert result["metadata"]["pipeline_type"] == "costo_menor_optimized"
   ```

---

## HITO 7: Capacidad de "What-If" Analysis

### Objetivo
Permitir al usuario simular diferentes escenarios y evaluar su impacto antes de decidir.

### Componentes a Construir

#### 7.1 Scenario Simulator
**Ubicación:** `backend/app/simulation/scenario_simulator.py`

```python
class ScenarioSimulator:
    """
    Ejecuta simulaciones de "qué pasaría si..." para diferentes estrategias.
    """

    async def simulate_proposal_variants(
        self,
        session_id: str,
        base_data: Dict,
        variants: List[ProposalVariant]
    ) -> SimulationReport:
        """
        Cada variante es una propuesta diferente:
        - Variante A: Precio conservador (+10% sobre base)
        - Variante B: Precio agresivo (-5% sobre base)
        - Variante C: Solo requisitos obligatorios (sin opcionales)
        """

@dataclass
class ProposalVariant:
    name: str
    price_adjustment: float  # % sobre precios base
    include_optional_requirements: bool
    risk_tolerance: str  # "low", "medium", "high"

@dataclass
class SimulationResult:
    variant_name: str
    estimated_score: float  # Puntaje estimado según criterios
    compliance_rate: float  # % de requisitos cumplidos
    risk_score: float  # 0-1, riesgo de descalificación
    win_probability: float  # Probabilidad estimada de ganar
    recommendations: List[str]
```

#### 7.2 Sensitivity Analysis
```python
class SensitivityAnalyzer:
    async def analyze_critical_requirements(
        self,
        compliance_list: List[Requirement],
        company_profile: Dict
    ) -> SensitivityReport:
        """
        Identifica:
        1. Deal-breakers: Requisitos que si no se cumplen = descalificación segura
        2. High-impact: Requisitos que afectan mucho el score de evaluación
        3. Nice-to-have: Requisitos opcionales que dan puntos extra

        Retorna matriz de sensibilidad.
        """
```

#### 7.3 Scenario Comparison UI
**Frontend:** `frontend/src/components/ScenarioComparison.jsx`

**Funcionalidad:**
- Tabla comparativa de variantes
- Gráficas de radar (score, riesgo, cumplimiento, rentabilidad)
- Recomendación destacada: "Variante B tiene mejor relación riesgo/beneficio"
- Detalle por requisito: "En Variante C, falta cumplir: REQ-05, REQ-12"

#### 7.4 Monte Carlo Simulation
```python
class MonteCarloSimulator:
    async def run_win_probability_simulation(
        self,
        proposal: ProposalVariant,
        competitor_scenarios: List[CompetitorScenario],
        n_iterations: int = 10000
    ) -> MonteCarloResult:
        """
        Simula múltiples escenarios de competencia:
        - ¿Qué pasa si hay 3 competidores vs 10?
        - ¿Qué pasa si Competidor X participa (históricamente fuerte)?
        - Distribución de probabilidad de victoria
        """

        # Retorna:
        # - win_probability: 0-1
        # - confidence_interval: (lower, upper)
        # - key_factors: Qué variables más afectan el resultado
```

### Criterios de Aceptación (Tests)

1. **Test de Simulación de Variantes:**
   ```python
   async def test_variant_simulation():
       variants = [
           ProposalVariant("Conservador", price_adjustment=0.10, include_optional=True),
           ProposalVariant("Agresivo", price_adjustment=-0.05, include_optional=False),
       ]

       results = await simulator.simulate_proposal_variants(
           session_id="sess-001",
           base_data=mock_base_data,
           variants=variants
       )

       # Variante conservadora debe tener mayor compliance pero menor win_prob
       conservador = next(r for r in results if r.variant_name == "Conservador")
       agresivo = next(r for r in results if r.variant_name == "Agresivo")

       assert conservador.compliance_rate > agresivo.compliance_rate
       assert conservador.win_probability < agresivo.win_probability  # Asumiendo criterio costo
   ```

2. **Test de Análisis de Sensibilidad:**
   ```python
   async def test_sensitivity_analysis():
       requirements = [
           mock_req("REQ-01", mandatory=True, impact_score=0.9),
           mock_req("REQ-02", mandatory=True, impact_score=0.3),
           mock_req("REQ-03", mandatory=False, impact_score=0.1),
       ]

       analysis = await sensitivity_analyzer.analyze_critical_requirements(
           requirements,
           company_profile={"tiene_req_01": False}  # No cumple REQ-01
       )

       # REQ-01 debería ser identificado como deal-breaker
       assert "REQ-01" in [r.id for r in analysis.deal_breakers]
   ```

3. **Test de Monte Carlo:**
   ```python
   async def test_monte_carlo():
       result = await monte_carlo.run_win_probability_simulation(
           proposal=mock_proposal,
           competitor_scenarios=[mock_competitor_weak, mock_competitor_strong],
           n_iterations=1000
       )

       assert 0 <= result.win_probability <= 1
       assert len(result.confidence_interval) == 2
       assert result.key_factors  # Debe identificar factores clave
   ```

4. **Test E2E de What-If:**
   ```python
   async def test_what_if_e2e():
       # Procesar licitación
       base_result = await process_licitacion(mock_licitacion)

       # Ejecutar análisis de escenarios
       scenarios = await run_scenario_analysis(
           session_id=base_result.session_id,
           variants=["conservative", "aggressive", "balanced"]
       )

       # Verificar estructura completa
       assert "conservative" in scenarios
       assert "aggressive" in scenarios
       assert all(hasattr(s, "win_probability") for s in scenarios.values())

       # Verificar recomendación
       recommendation = scenarios["recommendation"]
       assert recommendation["variant"] in ["conservative", "aggressive", "balanced"]
       assert "reasoning" in recommendation
   ```

---

## TEST E2E FINAL: Validación Completa del Sistema Inteligente

### Escenario de Prueba Integral

```python
async def test_e2e_intelligent_system():
    """
    Test end-to-end que valida todos los hitos implementados.
    """

    # === SETUP ===
    # 1. Seed de experiencia previa
    await seed_experience_database([
        mock_licitacion_won(sector="salud", tipo="servicios"),
        mock_licitacion_lost(sector="salud", tipo="servicios"),
    ])

    # 2. Seed de datos de mercado
    await seed_market_data([
        {"item": "Limpieza hospitalaria", "precio": 25.0, "sector": "salud"},
        {"item": "Limpieza hospitalaria", "precio": 28.0, "sector": "salud"},
    ])

    # === EJECUCIÓN ===
    session_id = await create_session(company_id="comp-001")

    # Subir documento complejo
    await upload_document(session_id, mock_licitacion_salud_compleja)

    # Ejecutar procesamiento con TODAS las características inteligentes
    result = await orchestrator.process_intelligent(
        session_id=session_id,
        input_data={
            "company_id": "comp-001",
            "mode": "full_intelligent",
            "enable_experience": True,
            "enable_market_intel": True,
            "enable_what_if": True,
            "escalation_threshold": 0.7,
        }
    )

    # === VALIDACIONES ===

    # HITO 1: Memoria de Experiencia
    assert result["metadata"]["experience_applied"] == True
    assert "similar_cases_found" in result["metadata"]
    assert len(result["metadata"]["similar_cases_found"]) > 0

    # HITO 2: Razonamiento Multi-Paso
    assert result["metadata"]["refinements_applied"] >= 0  # Puede ser 0 si todo perfecto
    assert "validation_passed" in result["metadata"]

    # HITO 3: Confianza
    assert "confidence_scores" in result
    assert all(c.overall > 0.5 for c in result["confidence_scores"])  # O escaló
    assert "escalated_items" in result  # Items que necesitan revisión humana

    # HITO 4: Inteligencia de Mercado
    assert "market_comparison" in result["economic"]
    assert result["economic"]["competitiveness_score"] is not None

    # HITO 5: Feedback (simular)
    await submit_mock_feedback(session_id, [
        {"field": "criterio_evaluacion", "correction": "Puntos y Porcentajes"},
    ])
    feedback_stored = await get_feedback(session_id)
    assert len(feedback_stored) == 1

    # HITO 6: Orquestador Adaptativo
    assert result["metadata"]["pipeline_config"]["adaptive"] == True
    assert result["metadata"]["stages_executed"] > 0

    # HITO 7: What-If
    assert "scenario_analysis" in result
    assert len(result["scenario_analysis"]["variants"]) >= 2
    assert "recommendation" in result["scenario_analysis"]

    # === VALIDACIÓN DE CALIDAD ===
    # El resultado debe ser significativamente mejor que el pipeline básico
    assert result["aggregate_health"] in ["ok", "partial"]  # No "failed"

    # Métricas de calidad
    assert result["compliance"]["data"]["total_count"] > 0  # Extrajo requisitos
    assert result["economic"]["status"] != "error"

    print("✅ Test E2E de Sistema Inteligente PASÓ")
    return True
```

### Métricas de Éxito del Sistema Inteligente

| Métrica | Pipeline Básico | Sistema Inteligente | Mejora Esperada |
|---------|-----------------|---------------------|-----------------|
| Precisión de extracción | ~75% | >90% | +15% |
| Tasa de falsos positivos | ~20% | <5% | -15% |
| Requisitos críticos perdidos | ~5% | <1% | -4% |
| Tiempo de revisión humana | 100% | ~20% | -80% |
| Probabilidad de ganar (estimada) | N/A | ±15% real | Nueva |
| Adaptabilidad a nuevos formatos | Baja | Alta | Nueva |

---

## Checklist de Implementación

### Fase 1: Fundamentos (Hitos 1-3)
- [ ] Experience Store con PostgreSQL
- [ ] Communication Bus para agentes
- [ ] Confidence Scorer con múltiples señales
- [ ] Tests unitarios para cada componente
- [ ] Tests de integración agente-agente

### Fase 2: Integración (Hitos 4-5)
- [ ] Conectores a fuentes de mercado
- [ ] Sistema de feedback UI + backend
- [ ] RLHF básico (análisis de tendencias)
- [ ] Integración con orchestrator

### Fase 3: Inteligencia Avanzada (Hitos 6-7)
- [ ] Pipeline Configurator dinámico
- [ ] Scenario Simulator con Monte Carlo
- [ ] UI de comparación de escenarios
- [ ] Checkpointing avanzado

### Fase 4: Validación
- [ ] Test E2E completo pasa
- [ ] Benchmark contra pipeline básico
- [ ] Validación con usuarios reales
- [ ] Documentación completa

---

## Notas para el Implementador

1. **Modularidad:** Cada hito debe poder activarse/desactivarse via feature flags
2. **Backward Compatibility:** El pipeline básico debe seguir funcionando
3. **Observabilidad:** Todo decision point debe loggearse para debugging
4. **Testing:** Cada hito requiere tests unitarios + integración + E2E
5. **Performance:** El sistema inteligente será más lento; considerar caching

---

*Documento creado el: 2026-03-30*
*Versión: 1.0*
*Autor: Claude Code (Análisis de Arquitectura)*