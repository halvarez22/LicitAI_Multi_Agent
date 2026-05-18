# Diseño: Document Field Policy Registry + Confidence Gate

## Arquitectura propuesta

Se extiende el `DocumentFillQualityGateService` con dos componentes:

1. `DocumentFieldPolicyRegistry`
2. `FieldProvenanceResolver`

Flujo:
1) writer genera archivos  
2) gate resuelve política por archivo  
3) gate extrae campos y evalúa reglas por política  
4) gate consulta procedencia/confianza por campo  
5) gate emite issues + métricas + hints para orquestador/UI

## Componente 1: DocumentFieldPolicyRegistry

### Estructura de política

```json
{
  "policy_version": "1.1.0",
  "family": "economic",
  "document_match": {
    "template_id": "anexo_ae",
    "filename_regex": "ANEXO_AE_.*\\.docx"
  },
  "fields": [
    {
      "field_key": "razon_social",
      "required": true,
      "allow_placeholder": false,
      "expected_type": "text",
      "min_confidence": 0.85
    },
    {
      "field_key": "subtotal",
      "required": true,
      "allow_placeholder": false,
      "expected_type": "numeric",
      "consistency_group": "economic_totals",
      "min_confidence": 0.95
    }
  ]
}
```

### Resolución de política (orden)
1. Match por `template_id`.
2. Match por `tipo` del documento.
3. Match por regex de filename.
4. Fallback por familia.

Si no hay política específica, usar policy base de familia + warning de cobertura.

## Componente 2: FieldProvenanceResolver

Responsable de exponer procedencia por campo crítico:
- `source` (`user_override`, `normalized_doc`, `master_profile`, `llm_inference`)
- `confidence` (0..1)
- `anchor` (opcional: doc/página/snippet)

### Cascada de precedencia
`user_override > normalized_doc > master_profile > llm_inference`

El resolver no decide contenido; solo reporta procedencia del valor ya usado.

## Validadores por tipo

### Text
- no vacío, no placeholder si la policy lo prohíbe.

### Numeric
- coerción segura y formato numérico válido.
- opcionalmente rango mínimo/máximo.

### Date
- parseo en formato esperado y coherencia básica.

### Identifier
- validaciones sintácticas (ej. RFC patrón básico configurable).

## Consistencia cruzada

`consistency_group: economic_totals`
- subtotal, iva, total deben ser numéricos.
- `total ~= subtotal + iva` con tolerancia configurable.

## Salida del gate (extendida)

```json
{
  "validation_passed": true,
  "policy_version": "1.1.0",
  "documents_scanned": 3,
  "documents_with_policy": 3,
  "blocking_count": 0,
  "warning_count": 2,
  "issues": [ /* ... */ ],
  "metrics": {
    "mode": "audit",
    "policy_miss_count": 0,
    "confidence_violations": 1
  }
}
```

## Integración planificada (sin implementar aún)

- `backend/app/services/document_fill_quality_gate.py`
  - consumir `DocumentFieldPolicyRegistry`
  - consumir `FieldProvenanceResolver`
- writers:
  - pasar metadatos de documento (`template_id`, `tipo`, `filename`)
- orchestrator:
  - persistir hints extendidos con `policy_version`.

## Estrategia de rollout

1. Audit mode con políticas mínimas (core docs).
2. Medir falsos positivos + policy misses.
3. Enforce parcial en campos críticos (identidad + económicos).
4. Enforce total tras estabilización.

## Riesgos y mitigaciones

- Riesgo: divergencia entre naming real y reglas de match.
  - Mitigación: fallback por familia + telemetría `policy_miss_count`.
- Riesgo: falta de trazabilidad por campo en datos heredados.
  - Mitigación: resolver con fallback explícito `source=unknown`, severidad warning en audit.
