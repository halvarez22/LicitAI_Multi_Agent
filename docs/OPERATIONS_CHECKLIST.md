# Checklist de operación — calidad, Oracle y auditoría

Use este checklist después de un cambio relevante o de una corrida E2E en una sesión real.

## 1. Entorno

- [ ] Ollama en el host responde (`11434`).
- [ ] `docker compose ps`: `backend`, `database`, `vector-db`, `redis` sanos.
- [ ] `.env` alineado con [.env.example](../.env.example) (sin commitear secretos).

## 2. Tras una corrida de pipeline (cualquier resultado)

- [ ] Existe `backend/out/metadata/latest_job.json` **solo** si el orquestador cerró y persistió telemetría (éxito o descalificación dura).
- [ ] Revisar `metadata.telemetry.stages.*.duration_seconds` para análisis de rendimiento.

## 3. Export y Oracle

Desde `backend/` (PostgreSQL accesible con la misma URL que en contenedor o `localhost` expuesto):

```powershell
python scripts/export_oracle_inputs.py --session-id <SESSION_ID> --out out/oracle_real
python scripts/run_oracle.py --analysis out/oracle_real/analysis.json --compliance out/oracle_real/compliance.json --economic out/oracle_real/economic.json --out out
```

- [ ] Salida: `blocking_issues: 0` y código de salida `0` (salvo que estés validando un caso rojo a propósito).
- [ ] Si existe `out/oracle_real/packager.json`, añadir `--packager out/oracle_real/packager.json` a `run_oracle.py`.

## 4. Reporte de auditoría (legal/ops)

```powershell
python scripts/generate_audit_report.py --session-id <SESSION_ID> --out out/audit
```

- [ ] `out/audit/<SESSION_ID>/audit_report.json` parseable.
- [ ] `audit_summary.csv` con cabeceras esperadas.
- [ ] `compliance_gate` coherente con `stop_reason` (p. ej. `COMPLIANCE_GATE_BLOCKING`).

## 5. Agnosticismo (post–Fase F)

```powershell
python scripts/run_agnosticism_validation.py scan
python scripts/run_agnosticism_validation.py finalize --session-id <SESSION_ID>
```

- [ ] `out/agnosticism_findings.txt`: sin entradas **CRITICAL** (slugs de sesión en `app/`).
- [ ] `finalize` termina sin error (export + oracle + audit).

## 6. Regresión automatizada (subset habitual)

Desde `backend/` con `PYTHONPATH=.`:

```powershell
pytest tests/test_performance.py tests/test_oracle.py tests/test_compliance_gate.py tests/test_agent_hardening_v4.py tests/test_template_lock.py tests/test_packager.py tests/test_audit_report.py tests/test_agnosticism_validation.py -q
```

- [ ] Todo en verde en CI o en un venv alineado con `requirements.txt`.
