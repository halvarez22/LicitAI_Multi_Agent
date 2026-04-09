# LicitAI

Sistema multi-agente para extracción, análisis forense de cumplimiento y generación de propuestas en licitaciones (FastAPI + React + PostgreSQL + ChromaDB + Ollama en host).

![Oracle Validation](https://github.com/halvarez22/LicitAI_Multi_Agent/actions/workflows/oracle-validation.yml/badge.svg)

## Inicio rápido (Docker)

1. **Ollama en el host** (recomendado en Windows): modelo configurado vía `OLLAMA_MODEL` (p. ej. `llama3.1:8b`), API en `http://127.0.0.1:11434`.
2. Copia variables: `cp .env.example .env` y ajusta credenciales y rutas.
3. Desde la raíz del repo:

```bash
docker compose up -d --build
```

- **API backend:** `http://127.0.0.1:8001` (mapeo `8001:8000`).
- **Frontend:** puerto publicado en `docker-compose.yml` (p. ej. `8504`).
- **Salidas en disco:** en Windows el compose monta `C:/data` → `/data` en el contenedor; las sesiones suelen escribir bajo `/data/outputs/<session_id>`.

Documentación detallada: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Arquitectura y contratos

- Visión de agentes, CompraNet y flujo forense: [CLAUDE.md](CLAUDE.md) (reglas del workspace).
- Variables de entorno (referencia amplia): [.env.example](.env.example) y [backend/ENV_VARS.md](backend/ENV_VARS.md).

## Operación, calidad y auditoría

Checklist de operador (Oracle, auditoría de sesión, agnosticismo): [docs/OPERATIONS_CHECKLIST.md](docs/OPERATIONS_CHECKLIST.md).

## Scripts útiles (desde `backend/`)

| Script | Uso |
|--------|-----|
| `scripts/run_oracle.py` | Validación contra oracle JSON + reporte en `out/` |
| `scripts/export_oracle_inputs.py` | Exporta `analysis/compliance/economic` desde PostgreSQL |
| `scripts/generate_audit_report.py` | `audit_report.json` + CSV para legal/ops |
| `scripts/run_agnosticism_validation.py` | `scan` (acoplamientos en `app/`) y `finalize` post-E2E |
| `scripts/e2e_monitor_job.py` | POST + polling de job (variables `E2E_*`) |

## Problemas frecuentes

Ver [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Estado CI

- Workflow Oracle: `.github/workflows/oracle-validation.yml` (badge arriba).
