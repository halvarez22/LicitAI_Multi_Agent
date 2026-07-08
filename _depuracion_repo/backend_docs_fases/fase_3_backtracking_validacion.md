# Fase 3 — Backtracking, validación cruzada y capa de reflexión (MVP)

## Introducción
Esta fase implementa la capacidad del sistema LicitAI para detectar inconsistencias entre el análisis técnico (`AnalystAgent`) y el cumplimiento forense (`ComplianceAgent`), permitiendo una re-ejecución focalizada (Backtracking) para mejorar la calidad de los resultados finales.

## Diagrama de Flujo del Proceso
```text
[Input] -> AnalystAgent -> ComplianceAgent
              |                |
              V                V
      [ValidatorAgent (Deterministic Validation)]
              |
              V
      [CriticAgent (Reflection Layer)]
              |
      /--------------- verdict ---------------\
      |                   |                   |
   [Accept]      [Rerun Agent X]      [Escalate Human]
      |                   |                   |
   Continue          Refined Input      Stop & Report
   Pipeline           (Backtrack)
```

## Componentes de Fase 3

### 1. RedisAgentBus (`backend/app/agents/communication/redis_bus.py`)
- **Propósito**: Canal de comunicación asíncrono y persistente entre agentes.
- **Mecanismo**: Usa colas Redis (`LPUSH`/`RPOP`) con TTL de 24 horas.
- **Canal**: `licitai:agents:{session_id}`.

### 2. ValidatorAgent (`backend/app/agents/validator.py`)
- **Lógica**: Determinística (sin LLM por defecto).
- **Validaciones**:
  - **Cobertura**: Verifica que todos los requisitos detectados por el Analyst existan en la lista maestra de Compliance.
  - **Confianza**: Detecta si el score de confianza de algún agente cae por debajo del umbral crítico (0.40).
- **Salida**: `ValidationReport` con una lista de conflictos y sugerencias de corrección.

### 3. CriticAgent (`backend/app/agents/critic.py`)
- **Propósito**: Tomar la decisión final sobre el rumbo del pipeline basado en el reporte de validación.
- **Veredictos**:
  - `accept`: Todo correcto o inconsistencias menores.
  - `rerun_analyst`: Requiere refinar el análisis técnico.
  - `rerun_compliance`: Requiere corregir la lista de cumplimiento.
  - `escalate_human`: Fallo crítico o se alcanzó el límite de iteraciones.

### 4. Orquestador Adaptativo (`backend/app/agents/orchestrator.py`)
- Gestiona el bucle de backtracking.
- Enriquece el `AgentInput` con datos de refinamiento (`refinement`):
  - `iteration`: Número de iteración actual.
  - `hints`: Sugerencias textuales de corrección.
  - `focus_req_ids`: IDs específicos que requieren revisión.

## Criterios de Parada y Límites
- **BACKTRACK_MAX_ITERATIONS**: 2 (Configurable en `settings.py`).
- **Safety Gate**: Si se alcanza el máximo de iteraciones y persisten conflictos críticos, el sistema escala a revisión humana.
- **Costo**: El Critic limita las llamadas adicionales a LLM (normalmente 1 por re-run).

## Configuración (Feature Flags)
```python
BACKTRACKING_ENABLED = True  # Por defecto False
BACKTRACK_MAX_ITERATIONS = 2
VALIDATOR_LLM_ASSIST = False # Usar LLM en el Validator (experimental)
CRITIC_ENABLED = True        # Solo opera si BACKTRACKING_ENABLED es True
```

## Riesgos y Mitigaciones
- **Bucles Infinitos**: Mitigado por el límite estricto de iteraciones.
- **Latencia**: El backtracking añade tiempo de procesamiento; se recomienda solo para documentos de alta complejidad o criticidad.
- **Redis Down**: El sistema maneja fallos en Redis de forma resiliente, continuando el pipeline sin backtracking si el bus no está disponible.
