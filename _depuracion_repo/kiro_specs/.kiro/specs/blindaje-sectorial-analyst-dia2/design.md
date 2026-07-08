# Diseño: Día 2 — Clasificación Sectorial (Analyst)

## Alcance

Fase de diseño para incorporar clasificación sectorial en backend, centrada en:
- `backend/app/agents/analyst.py`
- ajustes menores de prompts (`enhanced_prompts` o bloque equivalente)
- contrato aditivo en `extracted_data`

Sin activar bloqueos duros en esta etapa.

## Arquitectura propuesta

### 1) Nuevo bloque de salida canónica

Agregar en `extracted_data`:

```json
{
  "sector_classification": {
    "sector_id": "obra_publica",
    "confidence": 0.86,
    "method": "hybrid",
    "scores": {
      "obra_publica": 0.86,
      "salud": 0.11,
      "adquisiciones": 0.22,
      "servicios": 0.18,
      "tic": 0.07
    },
    "evidence": [
      {
        "signal_code": "OP_ANALISIS_PRECIOS_UNITARIOS",
        "snippet": "deberá presentar análisis de precios unitarios...",
        "source_hint": "anexo técnico/económico",
        "weight": 0.35
      }
    ],
    "decision_reason": "Top score dominante por señales de obra pública",
    "version": "sector-v1"
  }
}
```

### 2) Pipeline de decisión (hybrid)

1. **Extracción de señales rule-based**
   - diccionario de patrones por sector (regex + keywords normalizadas).
2. **Refuerzo LLM asistido**
   - prompt específico devuelve hipótesis de sector y evidencias literales.
3. **Fusión y scoring**
   - ponderar señales rule-based + LLM.
4. **Resolución conservadora**
   - `mixto` o `indeterminado` según umbral de diferencia/confianza.

## Modelo de señales por sector (v1)

### Obra pública
- Señales: `análisis de precios unitarios`, `catálogo de conceptos`, `programa de obra`, `maquinaria y equipo`, `residente/superintendente`, `volúmenes de obra`.

### Salud
- Señales: `registro sanitario`, `COFEPRIS`, `cadena de frío`, `lote/caducidad`, `farmacovigilancia`.

### Adquisiciones/Suministro
- Señales: `partidas`, `fichas técnicas`, `entrega de bienes`, `garantía de fabricante`, `muestras`.

### Servicios generales
- Señales: `perfil de personal`, `niveles de servicio`, `SLA`, `metodología operativa`, `cobertura`.

### TIC
- Señales: `licenciamiento`, `infraestructura TI`, `ciberseguridad`, `mesa de ayuda`, `integraciones API`.

## Contratos internos

### Dataclass sugerida (backend)

- `SectorEvidence`:
  - `signal_code: str`
  - `snippet: str`
  - `source_hint: str`
  - `weight: float`

- `SectorClassification`:
  - `sector_id: str`
  - `confidence: float`
  - `method: str`
  - `scores: Dict[str, float]`
  - `evidence: List[SectorEvidence]`
  - `decision_reason: str`
  - `version: str`

## Reglas de decisión

- `THRESHOLD_CONF_MIN = 0.55`
- `THRESHOLD_DELTA_MIXTO = 0.10`

Resolución:
- si `top_score < THRESHOLD_CONF_MIN` -> `indeterminado`
- si `(top_score - second_score) < THRESHOLD_DELTA_MIXTO` -> `mixto`
- en otro caso -> `sector_id = top_sector`

## Prompting (ajuste mínimo)

Incluir instrucción explícita:
- “Identifica sector dominante y devuelve **solo** evidencias textuales presentes en las bases.”
- “No infieras sector sin cita literal.”
- “Si la evidencia es insuficiente, marca indeterminado.”

## Observabilidad y trazabilidad

Registrar en logs estructurados:
- `sector_id`,
- `confidence`,
- `top_signals`,
- `classification_method`,
- `fallback_reason` (cuando aplique `mixto/indeterminado`).

## Riesgos y mitigaciones

- Riesgo: sobreajuste por keywords aisladas.
  - Mitigación: exigir mínimo 2 señales o una señal de alto peso + evidencia literal.

- Riesgo: sesgo del LLM hacia “servicios”.
  - Mitigación: peso base rule-based y salida conservadora (`indeterminado`).

- Riesgo: romper contratos actuales.
  - Mitigación: campo aditivo; no reemplazar claves existentes.

## Estrategia de rollout

1. `shadow mode` por defecto (solo diagnóstico).
2. calibración con suite vertical (día 3/4 del roadmap).
3. activación progresiva de consumo en Intake/DataGap cuando precisión sea estable.
