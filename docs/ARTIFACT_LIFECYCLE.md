# Ciclo de vida de artefactos de sesión

Política universal para **invalidación**, **preservación** y **reconstrucción** tras cambio de bases, re-análisis o generación. Sin reglas por licitación.

**Implementación:** `session_bases_analysis_invalidation.py`, `analysis_artifacts_rehydrate_service.py`, orquestador.

---

## 1. Huella de bases (`bases_analysis_snapshot`)

| Campo | Significado |
|-------|-------------|
| `fingerprint` | SHA-256 truncado del set de PDFs de bases/convocatoria |
| `pending_reanalysis` | `true` → análisis/compliance no confiables para la huella actual |
| `invalidated_at` / `reason` | Auditoría de la última invalidación |

**Disparadores de invalidación:** upload/reemplazo de bases, cambio de texto ingestado, `force_invalidate_analysis_artifacts`.

---

## 2. Qué se borra al invalidar análisis

Función: `strip_analysis_artifacts` / `apply_analysis_invalidation`.

### Tasks eliminados de `tasks_completed`

- `stage_completed:analysis`
- `stage_completed:compliance`
- `analisis_bases`, `master_compliance_list`, `go_no_go_result`

### Claves de sesión eliminadas

| Clave | Efecto en UI |
|-------|----------------|
| `compliance_master_list` | Dictamen / zonas de requisitos |
| `document_inventory`, `intake_plan` | Inventario y plan intake |
| `analyst_result`, `analysis_result` | Resultado crudo analista |
| `forensic_dictamen`, `dictamen_forense`, `dictamen` (si presente en limpieza extendida) | Dictamen forense |
| `junta_aclaraciones_questions` | Preguntas junta |
| `mini_dictamen_anexos`, `delivery_coverage_report` | Anexos / cobertura |
| `last_orchestrator_decision` | Stop reason previo |

---

## 3. Qué se conserva (por diseño)

Documentado en `PRESERVED_TOP_LEVEL_KEYS` (rehydrate) e invalidación:

| Clave | Motivo |
|-------|--------|
| `economic_user_inputs`, `session_line_items` | Captura HITL económica |
| `generation_state` | Cola formats → packager |
| `go_no_go_override` | Decisión usuario Go/No-Go |
| `pending_questions` | Cola chat HITL (salvo hard reset) |
| `submission_checklist` | Hitos persistidos (puede quedar desalineado → rehydrate) |
| `document_candidates_*` | Hasta rehydrate o nuevo análisis |
| Outputs en disco `/data/outputs/{session_id}/` | No se borran en invalidación automática |

**Hard reset** (`should_hard_reset_session_artifacts`): solo en modo `full` cuando **cambió la huella de bases**. Limpia además `pending_questions`, `document_inventory`, candidatos v1, `economic_user_inputs` (orquestador). **No** aplica en `analysis_only` ni `generation*`.

---

## 4. Quién reconstruye qué

| Artefacto | Reconstructor | Cuándo |
|-----------|---------------|--------|
| Compliance + dictamen | Orquestador → Compliance / Analyst | «Analizar bases» (job async `/agents/process`) |
| Candidatos documentales | `ensure_session_document_candidates` | Rehydrate o dictamen lazy |
| Hitos / calendario | `ensure_session_cronograma_and_checklist` | Rehydrate; fast-path si checklist válido |
| Junta aclaraciones | `junta_aclaraciones_questions_service` | Rehydrate o post-compliance hook |
| Snapshot committed | `commit_bases_analysis_snapshot` | Fin de pipeline análisis o rehydrate OK |

**Servicio unificado:** `rehydrate_after_analysis_pipeline` (POST `/sessions/{id}/rehydrate-analysis-artifacts`).

---

## 5. Flujo recomendado operativo

```mermaid
flowchart TD
  upload[Upload / cambio bases] --> sync[sync_bases_analysis_state]
  sync -->|fingerprint distinto| inv[strip_analysis_artifacts]
  inv --> pending[pending_reanalysis=true]
  pending --> analyze[POST /agents/process job async]
  analyze --> hook[orchestrator post-compliance rehydrate]
  hook --> committed[snapshot committed]
  committed --> ui[UI: health healthy]
  pending -->|artefactos parciales| manual[POST rehydrate async]
  manual --> ui
```

---

## 6. Señales de salud (`GET /sessions/{id}/health`)

- `rehydrate_recommended=true` → ejecutar rehydrate (async) o re-analizar.
- `stale` incluye: `bases_pending_reanalysis`, `dictamen_missing_with_compliance`, `baseline:…`.
- `healthy=true` → paneles pueden servirse sin trabajo pesado en GET.

---

## 7. Anti-patrones (no hacer)

- Borrar `economic_user_inputs` en invalidación suave (pierde HITL).
- Llamar enrichment RAG de cronograma en cada GET `/dictamen` (P0-03).
- Parchear conteos por sesión en lugar de rehydrate/baseline.
- Hard reset en `generation_only` (rompe cola de generación).

---

## 8. Referencias

- Rehydrate: `backend/app/services/analysis_artifacts_rehydrate_service.py`
- Invalidación: `backend/app/services/session_bases_analysis_invalidation.py`
- Smoke: `scripts/smoke_session_stability.py`, `scripts/smoke_ui_artifacts.py`
- Handoff: `docs/INFORME_ESTABILIZACION_HANDOFF.md`
