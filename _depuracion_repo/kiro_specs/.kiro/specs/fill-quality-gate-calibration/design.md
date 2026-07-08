# Diseño: Calibración técnica del Fill Quality Gate

## Alcance

Este diseño cubre el framework de calibración del gate existente, sin rediseñar la arquitectura base de validación documental.

Incluye:
- dataset etiquetado,
- runner de evaluación,
- cálculo de métricas,
- gobernanza de políticas y rollout.

## Arquitectura propuesta

### 1) `CalibrationCase` (modelo de prueba)

Cada caso de calibración define:
- `case_id`
- `stage` (`technical|formats|economic`)
- `document_type`
- `input_artifacts` (referencia a archivos materializados o fixtures)
- `expected_issues[]` (ground truth)
- `expected_blocking` (bool)

Ejemplo:

```json
{
  "case_id": "econ_placeholder_001",
  "stage": "economic",
  "document_type": "anexo_economico",
  "expected_issues": [
    {
      "error_type": "placeholder_detected",
      "field_key": "representante_legal",
      "severity": "block"
    }
  ],
  "expected_blocking": true
}
```

### 2) `FillGateCalibrationRunner`

Runner offline para ejecutar el gate contra el dataset y comparar con ground truth.

Flujo:
1. cargar `CalibrationCase[]`,
2. ejecutar `validate_generated_documents_fill(...)`,
3. normalizar salida a firmas comparables (`error_type + field_key + severity`),
4. computar matriz de confusión por regla,
5. emitir reporte.

### 3) Métricas y tablero técnico

Por `error_type`:
- TP, FP, TN, FN,
- precisión, recall, F1.

Global:
- blocking precision,
- blocking recall,
- false blocking rate,
- issue leakage rate (escape de errores críticos).

### 4) Política de calibración versionada

Definir archivo de política versionable (json/yaml):
- `policy_version`
- `min_confidence_critical`
- severidad por `error_type`
- allowlist por (`document_type`, `field_key`, `pattern`)
- reglas no relajables

La política se aplica por precedencia:
1. override explícito,
2. política por documento,
3. defaults globales.

### 5) Reportería

#### Reporte técnico (detallado)
- configuración evaluada,
- métricas por regla,
- top falsos positivos y falsos negativos,
- recomendaciones de ajuste por prioridad.

#### Reporte ejecutivo (compacto)
- estado semáforo:
  - verde: listo para enforce,
  - amarillo: enforce parcial,
  - rojo: mantener audit.
- impacto de negocio:
  - bloqueos evitados,
  - riesgo residual estimado.

## Estrategia de rollout

### Fase A — Baseline audit
- correr runner con política actual,
- establecer línea base de métricas.

### Fase B — Tuning iterativo
- ajustar umbrales/severidades por lotes pequeños,
- comparar métricas contra baseline.

### Fase C — Enforce parcial
- activar bloqueo solo para reglas críticas con alta precisión.

### Fase D — Enforce total condicionado
- activar reglas restantes solo si cumplen criterios de go/no-go.

## Criterios técnicos de go/no-go

- blocking precision >= 0.95
- blocking recall >= 0.90
- false blocking rate <= tolerancia definida por operación
- sin degradación en tiempos de generación más allá de presupuesto operativo

## Riesgos y mitigaciones

- Riesgo: dataset poco representativo.
  - Mitigación: muestreo por familia documental y casos límite.

- Riesgo: sobreajuste a fixtures de laboratorio.
  - Mitigación: incluir corridas con sesiones reales anonimizadas.

- Riesgo: deriva por nuevos templates.
  - Mitigación: recalibración periódica y gating por `policy_version`.
