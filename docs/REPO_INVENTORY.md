# Inventario de repositorio — LicitAI

**Versión:** 1.0.0 · **2026-07-08**  
**Clasificación HRU:** A app runtime · B calidad/ops obligatoria · C archivado · D externo

---

## A — App real (runtime)

| Ruta | Rol |
|------|-----|
| `backend/app/` | API FastAPI, agentes, servicios, contratos JSON |
| `frontend/src/` | UI React (paneles, chat, generación) |
| `docker-compose.yml` | Orquestación contenedores |
| `infra/` | Modelfiles Ollama |
| `scripts/init-db.sql` | Init PostgreSQL (montado en compose) |
| `.github/workflows/` | CI pytest + oracle |

---

## B — No runtime, pero parte del producto (NO mover)

| Ruta | Rol |
|------|-----|
| `backend/tests/` | Pytest + oracles (OR-01…12, CONTAM01) |
| `backend/scripts/smoke_*` | Gates deploy F10 / R5 |
| `backend/scripts/run_oracle.py`, `export_oracle_inputs.py` | CI oracle |
| `backend/scripts/e2e_*.py`, `run_pilot_smoke_hru.ps1` | E2E piloto |
| `docs/SPEC_*` | Normativa HRU activa |
| `docs/ESTANDAR_ENTERPRISE_CANONICO_HITL.md` | Estándar replicable |
| `docs/ARTIFACT_LIFECYCLE.md`, `DEPLOY_HARDENING_PLAYBOOK.md` | Operación |
| `docs/GUIA_PILOTO_ONPREM_HRU.md`, `PILOT_SIGNOFF_CHECKLIST.md` | Piloto |
| `docs/POST_DEPLOY_PILOTO_ISSSTE_VIGILANCIA.md` | Checklist post-push |
| `.env.example`, `backend/ENV_VARS.md` | Config documentada |
| `CLAUDE.md`, `AGENTS_CONTEXT.md`, `README.md` | Contexto IA/dev |

---

## C — Archivado en `_depuracion_repo/` (recuperable)

| Origen | Destino | Motivo |
|--------|---------|--------|
| `backend/*.py` (sueltos) | `backend_root_scripts/` | Diagnóstico / one-off, no importados |
| `backend/*.json` dumps | `backend_artefactos/` | Salida de agentes, no config |
| `backend/scripts/uat_*`, `verify_barda_*`, `validate_isapeg_*` | `scripts_cliente_uat/` | UAT por licitación |
| `backend/scripts/e2e_*_report.json` | `scripts_artefactos/` | Artefactos de corrida |
| `docs/corridas_*.json`, `corrida_tarde_*.json` | `docs_corridas/` | Métricas históricas |
| Reportes sprint / Tunning_* | `docs_historico/` | Planes cerrados |
| `backend/docs/fase_*.md` | `backend_docs_fases/` | Hardening fases 0–5 |
| `frontend/src/*.bak` | `frontend_backups/` | Backups editor |
| `repo-template/`, `Plantilla Corporativa/` | `plantillas/` | Boilerplate duplicado |
| `.kiro/specs/` | `kiro_specs/` | Specs diseño (supersedidos por docs/SPEC_*) |
| `services/ocr-vlm/` | `servicios_inactivos/` | Servicio comentado en compose |
| `REPORTE_TECNICO_*.md`, `response1.json`, Guía txt | `root_misc/` | Misc raíz |

---

## D — Externo / no versionado

| Ruta | Notas |
|------|-------|
| `licitai-estandares/` | Repo hermano (estándar), no submodule |
| `bases y convocatorias de prueba/` | Gitignored — PDFs locales |
| `backend/scripts/peek_*`, `_*.py` | Gitignored — diagnóstico local |
| `uploads/`, `data/`, `logs/` | Runtime local |

---

## Decisión experta — resumen

**App real = A + B.** Todo lo demás versionado que no alimenta runtime, CI ni normativa activa → **C** en `_depuracion_repo/`.

**No se borró nada.** Recuperación: ver [`_depuracion_repo/README.md`](../_depuracion_repo/README.md).

---

## Próximos pasos (agendados)

Ver [`POST_DEPLOY_PILOTO_ISSSTE_VIGILANCIA.md`](POST_DEPLOY_PILOTO_ISSSTE_VIGILANCIA.md):

1. `docker compose up -d --build backend`
2. `python scripts/smoke_expediente_readiness_integrity.py`
3. Sesión nueva `vigilancia_issste_mayo_v1` + Mayo y Torres desde el inicio

---

## Fase 2 depuración (futuro, no ejecutada)

- Auditar `backend/scripts/` repair/ops (~35) vs duplicados en servicios
- Consolidar docs `AGENDA_*` obsoletos
- `git filter-repo` para bases en historial (script en `scripts/git-filter-rm-bases.sh`, gitignored)
