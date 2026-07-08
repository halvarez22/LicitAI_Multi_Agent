# Diseño: Gate de calidad de llenado documental

## Resumen arquitectónico

Se introduce un **DocumentFillQualityGate** transversal a generación, ejecutado al final de cada writer:

1. Writer genera archivos (`technical_writer`, `formats`, `economic_writer`).
2. Gate abre y analiza contenido final (DOCX/XLSX + metadatos).
3. Gate produce reporte estructurado (`issues`, métricas, veredicto).
4. Si hay bloqueantes: retornar `WAITING_FOR_DATA` y publicar `validation_events`.
5. Si no hay bloqueantes: continuar flujo actual sin cambios.

## Componentes propuestos

### 1) `DocumentFillQualityGateService`
- Servicio puro, deterministic-first.
- Entrada:
  - `session_id`,
  - `stage` (`technical|formats|economic`),
  - `generated_documents[]` (ruta + tipo),
  - `master_profile`,
  - `provenance_context` (si disponible).
- Salida:
  - `validation_passed`,
  - `issues[]`,
  - `blocking_count`,
  - `warning_count`,
  - `documents_scanned`,
  - `metrics`.

### 2) `DocumentFieldPolicyRegistry` (matriz de campos críticos)
- Registro versionado por tipo de documento.
- Define:
  - campos obligatorios,
  - expresiones inválidas,
  - umbral mínimo de confianza por campo crítico,
  - reglas de consistencia cruzada.

### 3) Extractores de contenido materializado
- `DocxFieldExtractor`: texto por párrafo/tabla para detectar placeholders y vacíos.
- `XlsxFieldExtractor`: celdas clave y validaciones de texto/consistencia.
- Solo lectura; sin mutación de archivos.

### 4) Publicador de eventos UX
- Adaptador que traduce `issues[]` a `validation_events`.
- Usa `error_type` estable para mapeo de mensajes y acciones en UI.

## Modelo de datos de issue

```json
{
  "error_type": "required_field_missing",
  "severity": "block",
  "document_id": "ANEXO_AE_PROPUESTA_ECONOMICA.docx",
  "field_key": "representante_legal",
  "detected_value": "",
  "expected_rule": "non_empty_and_not_placeholder",
  "provenance": {
    "source": "master_profile",
    "confidence": 0.92,
    "anchor": "constancia_fiscal.pdf:p2"
  }
}
```

## Estrategia de reglas

### A) Reglas de placeholder
- Patrón global configurable:
  - `[dato]`, `[nombre]`, `{campo}`, `N/A`, `...`, `"Dato pendiente..."`, etc.
- En campos críticos, placeholder => bloqueante.
- En campos no críticos, placeholder => warning (configurable).

### B) Reglas de completitud por documento
- Validación de presencia mínima de campos críticos por familia.
- Ejemplo económico mínimo:
  - razón social,
  - RFC,
  - representante,
  - subtotal/IVA/total coherentes.

### C) Reglas de consistencia cruzada
- Verifica coherencia entre:
  - encabezado/pie/firma,
  - perfil maestro,
  - datos económicos consolidados.

### D) Reglas de confianza/procedencia
- Si campo crítico proviene de inferencia sin respaldo mínimo, emitir bloqueante `source_confidence_insufficient`.

## Integración por etapa

### TechnicalWriter
- Ejecutar gate tras `_save_docx` de cada archivo y antes de `record_task_completion`.
- Si falla, devolver `WAITING_FOR_DATA` con `data.document_fill_quality_gate`.

### Formats
- Ejecutar gate en cada documento final, incluyendo ruta de templates legales y ruta LLM fallback.
- Mantener integridad de template y sumar validación de llenado final.

### EconomicWriter
- Ejecutar gate sobre DOCX/XLSX finales además de validaciones económicas ya existentes.
- No reemplaza `total_base_cotizable`; lo complementa.

### Orchestrator
- Consolidar hints/metrics del gate de llenado y persistir en sesión:
  - `last_document_fill_quality_waiting_hints`.
- Exponerlos para UI y panel diagnóstico.

## Configuración (flags)

- `DOCUMENT_FILL_QUALITY_GATE_ENABLED` (bool)
- `DOCUMENT_FILL_QUALITY_GATE_MODE` (`audit|enforce`)
- `DOCUMENT_FILL_QUALITY_MIN_CONFIDENCE_CRITICAL` (float)
- `DOCUMENT_FILL_QUALITY_MAX_BLOCKING_ISSUES` (int; default 0 para enforce estricto)

## Rollout recomendado

1. **Fase A (audit):** reporta issues sin bloquear; calibrar reglas.
2. **Fase B (enforce parcial):** bloquear solo `placeholder_detected` y `required_field_missing` críticos.
3. **Fase C (enforce total):** activar también inconsistencias y baja confianza.

## Riesgos y mitigaciones

- Riesgo: falsos positivos por redacción libre.
  - Mitigación: matriz por documento + allowlist por campo.
- Riesgo: latencia adicional.
  - Mitigación: extractores ligeros, caché por hash de archivo.
- Riesgo: ruido UX.
  - Mitigación: consolidación por documento/campo y acciones sugeridas.

## Criterios de aceptación de diseño

- Existe contrato único de `issues[]` y `validation_result`.
- Existe matriz de campos críticos por las 3 familias documentales.
- Existe estrategia de rollout `audit/enforce`.
- Existe plan de integración con `validation_mapping` y UI.
