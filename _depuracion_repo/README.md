# Depuración de repositorio — carpeta de recuperación

**Fecha:** 2026-07-08  
**Propósito:** Contener archivos **fuera del runtime de la app** movidos desde rutas activas.  
**Recuperación:** `git mv _depuracion_repo/<subcarpeta>/<archivo> <ruta_original>` o copiar manualmente.

## Qué NO se movió (app real + operación obligatoria)

| Área | Motivo |
|------|--------|
| `backend/app/` | Runtime FastAPI + agentes + servicios |
| `backend/tests/` | Regresión y oracles CI |
| `backend/scripts/smoke_*` | Gates deploy piloto (F10, R5) |
| `backend/scripts/run_oracle.py`, `export_oracle_inputs.py`, `e2e_*` genéricos | CI / E2E |
| `frontend/src/` (sin `.bak`) | UI React |
| `docs/SPEC_*`, playbooks activos, `ESTANDAR_*`, `ARTIFACT_LIFECYCLE` | Gobernanza HRU |
| `docker-compose.yml`, `infra/`, `scripts/init-db.sql` | Despliegue |

## Subcarpetas

| Carpeta | Contenido |
|---------|-----------|
| `backend_root_scripts/` | Scripts sueltos en `backend/*.py` (diag, peek, one-off cliente) |
| `backend_artefactos/` | JSON dumps generados en `backend/` |
| `scripts_cliente_uat/` | UAT/validate por licitación (isapeg, barda, obra) |
| `scripts_artefactos/` | Reportes JSON sueltos en `backend/scripts/` |
| `docs_corridas/` | Corridas de prueba inteligencia (JSON) |
| `docs_historico/` | Reportes sprint, tuning LLM, planes cerrados |
| `backend_docs_fases/` | Docs fase 0–5 (hardening histórico) |
| `frontend_backups/` | `*.bak` del frontend |
| `plantillas/` | `repo-template/` + `Plantilla Corporativa/` (boilerplate) |
| `kiro_specs/` | Specs diseño Kiro (`.kiro/specs/`) |
| `servicios_inactivos/` | `services/ocr-vlm/` (desactivado en compose) |
| `root_misc/` | Reportes sueltos en raíz |

## Inventario completo

Ver [`docs/REPO_INVENTORY.md`](../docs/REPO_INVENTORY.md).
