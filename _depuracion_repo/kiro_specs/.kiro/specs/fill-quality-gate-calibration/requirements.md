# Requisitos: Calibración del Fill Quality Gate

## Contexto

El `DocumentFillQualityGate` ya está integrado y funcional.  
La necesidad actual no es crear otro gate, sino **calibrar su sensibilidad** para reducir simultáneamente:

1. falsos bloqueos (gate demasiado estricto), y  
2. escapes de documentos incompletos (gate demasiado laxo).

Este bloque se enfoca en exactitud operativa y confianza de negocio.

## Objetivo

Definir una calibración controlada del gate para que:
- bloquee de forma consistente errores críticos reales,
- minimice bloqueos innecesarios en documentos válidos,
- mantenga trazabilidad auditable por regla, documento y severidad.

## Requisitos funcionales

### R1 — Modo de calibración explícito
- El sistema debe soportar operación de calibración en `audit` y `enforce`.
- Debe poder habilitarse por configuración sin cambios de código en cada iteración.

### R2 — Dataset de calibración etiquetado
- Debe existir un conjunto de casos con etiqueta esperada por issue:
  - `true_positive`,
  - `false_positive`,
  - `true_negative`,
  - `false_negative`.
- Cobertura mínima por familia documental:
  - técnico,
  - administrativo,
  - económico.

### R3 — Métricas de desempeño del gate
- La calibración debe producir métricas por `error_type`:
  - precisión,
  - recall,
  - F1,
  - tasa de bloqueo por corrida.
- Debe existir desglose por severidad (`block`, `warn`) y por `stage`.

### R4 — Ajuste de umbrales y severidad por política
- Debe existir tabla de calibración para:
  - `DOCUMENT_FILL_QUALITY_MIN_CONFIDENCE_CRITICAL`,
  - severidad por `error_type`,
  - excepciones/allowlist por `field_key` y tipo de documento.
- Cambios de política deben versionarse.

### R5 — Protección de reglas no relajables
- Reglas críticas no pueden degradarse a warning sin aprobación explícita:
  - `required_field_missing` en campos críticos,
  - `placeholder_detected` en campos críticos económicos/legales.

### R6 — Salida ejecutiva y técnica de calibración
- Debe generarse reporte técnico con:
  - configuración evaluada,
  - métricas por regla,
  - recomendaciones de tuning.
- Debe generarse resumen ejecutivo con impacto operacional:
  - bloqueos evitados,
  - riesgos residuales,
  - decisión recomendada (`seguir audit` o `pasar a enforce`).

### R7 — Criterio de “go/no-go” a enforce
- Definir umbral mínimo para mover de `audit` a `enforce`:
  - precisión global en issues bloqueantes >= 95%,
  - recall en issues bloqueantes >= 90%,
  - tasa de falsos bloqueos dentro de tolerancia operativa.

## Requisitos no funcionales

### N1 — Reproducibilidad
- Misma configuración + mismo dataset debe producir mismas métricas.

### N2 — Observabilidad
- Cada corrida de calibración debe registrar:
  - policy version,
  - mode,
  - timestamp,
  - hash de dataset.

### N3 — No regresión de flujo productivo
- El proceso de calibración no debe alterar generación en sesiones activas fuera del entorno de prueba.

## Criterios de aceptación

- Existe pipeline de calibración con métricas por `error_type`.
- Existe política versionada de severidades/umbrales.
- Existe decisión documentada de avance o permanencia en `audit`.
- Existen evidencias trazables para justificar cada ajuste.
