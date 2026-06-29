# SPEC — Curación del Dictamen Forense y salud dual (extracción vs auditoría)

**Versión:** 1.0.0  
**Fecha:** 2026-06-23  
**Estado:** Aprobado para implementación  
**Estándar aplicable:** [`docs/ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](ESTANDAR_ENTERPRISE_CANONICO_HITL.md)

## Resumen ejecutivo

El panel **Dictamen Forense** hoy muestra el volcado crudo de `ComplianceAgent` (~300+ ítems) y un único semáforo (`COMPLETADO CON INCIDENCIAS`) que el usuario interpreta como fallo de lectura de bases. La extracción (ingesta OCR/indexación) y la auditoría forense (map-reduce LLM + validación literal) son **capas distintas** mezcladas en UI.

Esta especificación introduce:

1. **Verdad canónica curada** (`dictamen_curated_v1`) — obligaciones accionables del **licitante** vs archivo forense completo.
2. **Salud dual** — `extraction_health` (materia prima) separado de `forensic_audit_health` (calidad de auditoría).
3. **Filtros reutilizados** — extensión de [`document_deliverable_filter.py`](../backend/app/services/document_deliverable_filter.py), no duplicación.
4. **Trazabilidad** — cada ítem excluido de la vista default conserva `curation_reason` y permanece en archivo completo.

## Documentos del paquete

| Documento | Rol |
|-----------|-----|
| [`.kiro/specs/dictamen-curacion-licitante/requirements.md`](../.kiro/specs/dictamen-curacion-licitante/requirements.md) | Requisitos funcionales y no funcionales |
| [`.kiro/specs/dictamen-curacion-licitante/design.md`](../.kiro/specs/dictamen-curacion-licitante/design.md) | Arquitectura, contratos de datos, diagramas |
| [`.kiro/specs/dictamen-curacion-licitante/implementation_plan.md`](../.kiro/specs/dictamen-curacion-licitante/implementation_plan.md) | Plan cronológico por fases |
| [`.kiro/specs/dictamen-curacion-licitante/tasks.md`](../.kiro/specs/dictamen-curacion-licitante/tasks.md) | Checklist ejecutable con IDs de tarea |

## Problema de negocio (caso disparador)

Sesión tipo obra pública municipal:

- `REQUISITOS (TOTAL): 369` — mezcla obligaciones del licitante con preámbulo del convocante (*"La Directora General de Obra Pública cuenta con la facultad de suscribir actos jurídicos"*, pág. 8).
- `COMPLETADO CON INCIDENCIAS` — zonas PARTIAL/FAIL en compliance sin distinguir de extracción OK.
- Usuario concluye erróneamente que **no se leyeron las bases**.

## Métricas de éxito

| Métrica | Baseline (corrida problema) | Objetivo post-implementación |
|---------|----------------------------|------------------------------|
| Ítems en vista default del dictamen | ~329 compliance + ~40 otros ≈ 369 | Reducción **50–75%** (solo accionables) |
| Ítems convocante-boilerplate en vista default | >0 (ej. Directora General) | **0** |
| Usuario distingue extracción vs auditoría | No | **Sí** (dos badges) |
| `tipo_accion=informativo` visible por defecto | Sí | **No** (solo archivo completo) |
| Regresión Oracle / tests filtro | N/A | Verde |

## Trazabilidad de requisitos → implementación

| ID | Requisito | Componente principal | Fase |
|----|-----------|---------------------|------|
| R1 | Vista accionable default | `dictamen_curation_service` + `auditSummary.js` | 1 |
| R2 | Archivo forense completo opt-in | `AnalysisResults` + `ExportPDF` | 1 |
| R3 | Salud dual extracción/auditoría | `extraction_health_service` + UI badges | 2 |
| R4 | Metadata `audience` en ítems compliance | `compliance.py` reduce + prompt | 3 |
| R5 | Filtro narrativa convocante | `is_convocante_narrative()` | 1, 3 |
| R6 | Resiliencia bloques LLM vacíos | `compliance.py` + ops Ollama | 4 |
| R7 | Política `DICTAMEN_VIEW_MODE` | `settings.py` + playbook | 5 |

## Fuera de alcance (v1.0)

- Reescribir `ComplianceAgent` map-reduce desde cero.
- Garantizar `compliance.status=success` en el 100% de corridas (sigue siendo objetivo de hardening LLM, no bloqueante para curación UI).
- Sustituir dictamen por asesoría legal humana.

## Referencias de código actuales

- Volcado sin filtro UI: [`frontend/src/utils/auditSummary.js`](../frontend/src/utils/auditSummary.js) `processAuditResults`, `mapComplianceHallazgo`
- Filtros existentes (reutilizar): [`backend/app/services/document_deliverable_filter.py`](../backend/app/services/document_deliverable_filter.py)
- Omisión `informativo` en candidatos: [`backend/app/services/document_candidate_list_service.py`](../backend/app/services/document_candidate_list_service.py)
- Estado partial por zona: [`backend/app/agents/compliance.py`](../backend/app/agents/compliance.py) `_apply_zone_gate`, `_resolve_zone_status_for_llm_issues`
- Paridad backend dictamen: [`backend/app/utils/audit_processor.py`](../backend/app/utils/audit_processor.py)
