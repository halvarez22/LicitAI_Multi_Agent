# Informe de estabilización — handoff cliente (1 página)

**Proyecto:** LicitAI · **Sprint:** estabilización UI + anti-regresión · **Fecha:** junio 2026  
**Sesiones referencia:** `isapeg_servicios_de_limpieza` · `unaq-2026_paneles_solares` · `vigilancia_issste`

---

## Qué se estabilizó

| Área | Entregable | Beneficio |
|------|------------|-----------|
| **P0 UI** | Checklist paralelo al dictamen; paneles lazy (docs, formatos, junta); timeouts/fail-soft en cronograma y dictamen | UI poblada en segundos; worker único no se cuelga |
| **P1 Rehidratación** | `analysis_artifacts_rehydrate_service` + hook post-compliance + script one-shot | Re-análisis no deja junta/hitos vacíos |
| **P2 Anti-regresión** | `smoke_session_stability.py`, baselines, `smoke_ui_artifacts.py`, `GET /health` + banner UI | Gate reproducible antes de cada entrega |
| **P4 Generación** | Fix fill gate (fuga prompt LLM + subrayados legales); VIGILANCIA `FINAL_OK` end-to-end | Formatos → económica → packager sin `INCOMPLETE_FORMATS_DATA` |

**Estado smoke (última corrida):** 3/3 `verdict: OK` · generación `completed` · `stop_reason: FINAL_OK` en las tres sesiones.

---

## Métricas de referencia (conteos UI)

| Sesión | Hitos | Junta | Panel formatos (`sobre_1_tecnico`) | Generación |
|--------|-------|-------|-------------------------------------|------------|
| ISAPEG | 6 | 4 | 19 | FINAL_OK |
| UNAQ | 6 | 3 | 15 | FINAL_OK |
| VIGILANCIA | 6 | 5 | 31 | FINAL_OK |

*VIGILANCIA mantiene `checklist_at_risk=true` en smoke (checklist sin cronograma en analysis); la UI sirve hitos persistidos — comportamiento documentado, no bloqueante.*

---

## Cómo correr smoke (gate pre-demo / pre-merge)

**Prerrequisito:** contenedor backend arriba (`docker compose up -d`).

```bash
# 1) Estabilidad Postgres + checklist (sin HTTP)
docker exec licitaciones-ai-backend-1 python scripts/smoke_session_stability.py

# 2) APIs UI + dictamen (desde host; backend en 8001)
python backend/scripts/smoke_ui_artifacts.py --base-url http://127.0.0.1:8001 --all-reference

# 3) Pytest mínimo checklist / invalidación bases
cd backend && python -m pytest tests/test_submission_checklist.py tests/test_session_bases_analysis_invalidation.py -q
```

**Exit codes:** `0` = OK · `1` = WARN (lento) · `2` = FAIL (revertir cambio).

**Reparación one-shot** (sesiones ya analizadas):

```bash
docker exec licitaciones-ai-backend-1 python scripts/rehydrate_analysis_artifacts.py --all-reference
```

**Reanudar generación** (tras cerrar HITL económico):

```bash
docker exec licitaciones-ai-backend-1 python scripts/resume_session_generation.py vigilancia_issste
```

---

## Backlog acordado (fuera de este sprint)

| ID | Tema | Notas |
|----|------|-------|
| — | Chat / intención / UX conversacional | Ver `docs/SUPER_ISSUE_CHAT_INTENCION_Y_UX_CONVERSACIONAL.md` |
| — | HITL matriz captura económica universal | Issue documentado en agenda |
| — | Subir `uvicorn workers` | Solo con plan GPU |
| — | Hardcode por licitación | Explícitamente fuera de alcance |

**Completado en P3:** rehydrate async + `ARTIFACT_LIFECYCLE.md` + checklist PR.

## Rehydrate async (P3-01)

```bash
# UI: botón «Actualizar artefactos» → 202 + polling job
# CLI síncrono (scripts):
curl -X POST "http://127.0.0.1:8001/api/v1/sessions/vigilancia_issste/rehydrate-analysis-artifacts?sync=true"
```

---

## Demo cliente

Script paso a paso por pestaña: [`docs/DEMO_CLIENTE_3_SESIONES.md`](DEMO_CLIENTE_3_SESIONES.md)

**Checkpoint:** `checkpoint/p5-01-handoff`
