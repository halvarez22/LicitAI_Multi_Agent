# Fase 1: Confianza (ConfidenceScore) 🛡️

## Objetivo
Implementar un sistema determinístico para que el sistema "sepa cuándo no sabe", asignando puntuaciones de confianza a las extracciones y respuestas del LLM basándose en señales auditables.

## Metodología de Scoring

Se utiliza un promedio ponderado de cuatro señales clave para calcular un `overall_score` de 0.0 a 1.0.

### 1. Señales Utilizadas
| Señal | Peso | Lógica |
| :--- | :---: | :--- |
| **Evidencia Literal** | 40% | Valida si la extracción existe literalmente (o mediante fuzzy match) en el texto fuente. |
| **Certidumbre en el Lenguaje** | 30% | Penaliza el uso de términos ambiguos del LLM (ej: "quizá", "probablemente", "no especifica"). |
| **Riqueza de Contexto** | 15% | Valida que la fuente tenga la longitud mínima esperada para un análisis serio. |
| **Consistencia Estructural** | 15% | Valida que el output no esté vacío y cumpla con longitudes mínimas lógicas. |

### 2. Umbrales (Thresholds)
Configurables vía variables de entorno:
- `CONFIDENCE_THRESHOLD_DEFAULT`: **0.70** (Aceptable para mayoría de campos).
- `CONFIDENCE_THRESHOLD_CRITICAL`: **0.80** (Requerido para campos críticos como montos o fechas).

### 3. Recomendaciones Generadas
- **ACCEPT**: Score >= Umbral.
- **REVIEW**: Score está entre el Umbral y (Umbral - 0.15). Se recomienda revisión humana asistida.
- **REJECT**: Score < (Umbral - 0.15). Probable alucinación o dato no presente.
- **ESCALATE**: Score < Umbral en campos críticos marcados. Requiere atención inmediata.

---

## Implementación Técnica

### Flags de Control
- `CONFIDENCE_ENABLED`: Activa el modo activo de confianza.
- `CONFIDENCE_SHADOW_MODE`: (Default: True) Calcula scores y los incluye en logs/metadatos pero no altera el flujo del orquestador.

### Ejemplo de Salida (AgentOutput.data)
```json
{
  "requisitos_filtro": ["RFC", "Documento de Identidad"],
  "confidence": {
    "overall": 0.95,
    "breakdown": {
      "literal_evidence": 1.0,
      "certainty_language": 1.0,
      "context_richness": 1.0,
      "structural_consistency": 0.8
    },
    "threshold_passed": true,
    "recommendation": "accept",
    "unknowns": [],
    "ambiguities": ["Extracción sospechosamente corta"]
  }
}
```

## Limitaciones
- El cálculo de evidencia literal es sensible a la normalización de espacios (manejado mediante regex).
- El scoring es heurístico y no utiliza modelos de NLP externos para mantenerlatencia baja.
