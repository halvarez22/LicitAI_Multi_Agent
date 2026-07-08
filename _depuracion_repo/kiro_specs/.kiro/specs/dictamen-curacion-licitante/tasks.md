# Tasks — Curación Dictamen Forense (checklist ejecutable)

Referencia: [requirements.md](requirements.md) | [design.md](design.md) | [implementation_plan.md](implementation_plan.md)

---

## Fase 0 — Baseline

- [ ] **DC-000** Exportar `compliance.json` y `analysis.json` de sesión obra municipal (`backend/scripts/export_oracle_inputs.py --session-id <ID>`)
- [ ] **DC-001** Clasificar manualmente 50 ítems: `actionable` | `archival` | `ambiguo`
- [ ] **DC-002** Registrar baseline: `total=___`, `actionable_manual=___`, `convocante_noise=___`
- [ ] **DC-003** Capturar screenshot dictamen actual (antes) para comparación UAT

---

## Fase 1 — Curación + UI default

### Backend

- [ ] **DC-101** Implementar `is_convocante_narrative(nombre, descripcion, snippet) -> bool` en `document_deliverable_filter.py`
- [ ] **DC-102** Tests: Directora General / contratante → True; "el licitante deberá" → False
- [ ] **DC-103** Crear `dictamen_curation_service.py` con `curate_dictamen_for_licitante_view()`
- [ ] **DC-104** Enum `CurationReason` documentado y estable
- [ ] **DC-105** Integrar: omitir `informativo`, `is_procedural_noise`, `should_show` donde aplique
- [ ] **DC-106** Calcular `stats` y `filter_pipeline_version`
- [ ] **DC-107** Crear `test_dictamen_curation_service.py` (TC01–TC05)
- [ ] **DC-108** Hook en `orchestrator.py` tras `stage_completed:compliance` → persist `session_state["dictamen_curated_v1"]`
- [ ] **DC-109** Extender `audit_processor.py` para incluir `dictamen_curated`, `obligacionesDetectadas`
- [ ] **DC-110** Test paridad processor vs estructura esperada por frontend

### Frontend

- [ ] **DC-111** `auditSummary.js`: leer `dictamen_curated_v1` del payload si existe
- [ ] **DC-112** Mapear `actionable_items` → `causales` para vista default
- [ ] **DC-113** Conservar `causalesArchival` / `causalesRaw` para toggle
- [ ] **DC-114** Renombrar métrica UI: `obligacionesDetectadas` (fallback `totalRequisitos` si sin curated)
- [ ] **DC-115** `App.jsx` AnalysisResults: estado `verArchivoCompleto` + toggle
- [ ] **DC-116** Subtítulo: `(N registros en archivo forense)` cuando curated
- [ ] **DC-117** `ExportPDF.jsx`: sección accionables only por default
- [ ] **DC-118** UAT: contador default < 50% baseline; 0 Directora General en default

---

## Fase 2 — Salud dual

- [ ] **DC-201** Crear `extraction_health_service.py` + `compute_extraction_health(session_id)`
- [ ] **DC-202** Tests extraction: ANALYZED ok, UPLOADED failed, texto <100 degraded
- [ ] **DC-203** Builder `forensic_audit_health` desde compliance metrics/zones
- [ ] **DC-204** Crear `dictamen_ux_messages.py` con `build_dictamen_ux_guia(extraction, forensic)`
- [ ] **DC-205** Incluir health blocks en `dictamen_curated_v1`
- [ ] **DC-206** UI: dos badges (Lectura de bases / Auditoría forense) con colores independientes
- [ ] **DC-207** Reemplazar copy único `COMPLETADO CON INCIDENCIAS` cuando extraction ok
- [ ] **DC-208** Test: extraction ok + compliance partial → mensajes no contradictorios

---

## Fase 3 — Compliance origen

- [ ] **DC-301** Añadir bloque PERSPECTIVA LICITANTE al prompt `_extract_zone_chunk`
- [ ] **DC-302** Few-shot negativo Directora General / positivo "el licitante deberá"
- [ ] **DC-303** Función `stamp_audience_metadata(item)` en reduce pipeline
- [ ] **DC-304** Guard en must-have: skip si `audience==convocante`
- [ ] **DC-305** Tests regresión `test_compliance_dedup.py` o nuevo fixture obra municipal
- [ ] **DC-306** Corrida comparativa: archival_count antes/después en misma sesión re-analizada

---

## Fase 4 — Resiliencia LLM

- [ ] **DC-401** Revisar logs `compliance_block_empty` y `blocks_empty_response_count` por zona
- [ ] **DC-402** UX: listar bloques vacíos en `forensic_audit_health.detail`
- [ ] **DC-403** Tuning query `GARANTÍAS/SEGUROS` en `search_zones`
- [ ] **DC-404** Refinar `_apply_zone_gate`: distinguir `rag_empty` vs `low_match_quality`
- [ ] **DC-405** Documentar vars `COMPLIANCE_BLOCK_EXTRA_RETRIES` en playbook
- [ ] **DC-406** (Opcional) Endpoint/job retry bloques — spike + implement si viable
- [ ] **DC-407** Smoke 2× E2E mismo PDF; registrar en `docs/corridas_prueba_inteligencia_*.json`

---

## Fase 5 — Ops y cierre

- [ ] **DC-501** Añadir `DICTAMEN_VIEW_MODE`, `DICTAMEN_CURATION_ENABLED` a `settings.py` y `.env.example`
- [ ] **DC-502** Sección dictamen en `DEPLOY_HARDENING_PLAYBOOK.md`
- [ ] **DC-503** Addendum acta V.5: partial ya no es UX default aceptable
- [ ] **DC-504** (Opcional) Caso Oracle DICTAMEN01
- [ ] **DC-505** Extender `generate_audit_report.py` con stats curación
- [ ] **DC-506** UAT usuario final + sign-off
- [ ] **DC-507** Actualizar `AGENTS_CONTEXT.md` con link a SPEC (1 párrafo)

---

## Verificación CI (cada PR)

```powershell
cd backend
$env:PYTHONPATH="."
pytest tests/test_dictamen_curation_service.py tests/test_document_deliverable_filter.py tests/test_audit_report.py -q
```

Frontend (si hay tests):

```powershell
cd frontend
npm test -- --run auditSummary 2>$null
```

---

## Registro de cambios (completar al implementar)

| Fecha | PR | Tareas | Notas |
|-------|-----|--------|-------|
| | | | |
