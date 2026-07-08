# Post-deploy — Piloto ISSSTE (sesión limpia)

**Agendado:** tras push `3ac01d5` (HRU integridad expediente R0–R5)  
**Objetivo:** Validar backend con gates ON y arrancar sesión **`vigilancia_issste_mayo_v1`** sin contaminación Manavil.

---

## Checklist operativo

### 1. Rebuild backend

```powershell
cd c:\LicitAI_Multi_Agent\licitaciones-ai
docker compose up -d --build backend
docker compose logs --tail=80 backend
```

**Criterio:** contenedor `healthy`, sin traceback al arrancar.

### 2. Variables (.env)

Confirmar:

```env
LICITAI_READINESS_GATES_ENABLED=true
LICITAI_EXPEDIENTE_GUIDED_ENABLED=false
```

### 3. Smoke R5 (host o contenedor)

```powershell
cd backend
$env:PYTHONPATH='.'
python scripts/smoke_expediente_readiness_integrity.py
```

Opcional con API:

```powershell
$env:PILOT_API_BASE='http://127.0.0.1:8001/api/v1'
python scripts/smoke_expediente_readiness_integrity.py --session vigilancia_issste_mayo_v1
```

**Criterio:** `SMOKE OK: expediente readiness + integridad HRU (R5)`

### 4. Crear sesión limpia `vigilancia_issste_mayo_v1`

| Paso | Acción |
|------|--------|
| 4.1 | Nueva sesión con ID `vigilancia_issste_mayo_v1` (UI o API) |
| 4.2 | **Empresa desde el inicio:** Mayo y Torres (`co_1780079004578`, RFC `CMT160107S83`) |
| 4.3 | Subir bases ISSSTE vigilancia (PDFs limpios, sin mezclar FSR/GYN) |
| 4.4 | `POST /agents/process` — analizar bases |
| 4.5 | Captura económica completa en chat (matriz + motor HITL) |
| 4.6 | `GET /sessions/vigilancia_issste_mayo_v1/readiness` → `capture.ready=true`, `binding_valid=true` |
| 4.7 | Generar económica (`generation_mode=economic`) |
| 4.8 | `GET /downloads/artifacts?scope=economic` → `readiness_integrity_blocked=false`, RFC Mayo |

### 5. No reactivar UI guided aún

Mantener `EXPEDIENTE_GUIDED_ENABLED=false` hasta implementar handoff en [`SPEC_UI_READINESS_INTEGRATION_HRU.md`](SPEC_UI_READINESS_INTEGRATION_HRU.md).

### 6. Sesión legacy `vigilancia_issste`

**No reparar.** Archivar como referencia forense. Si se necesita bind:

```http
POST /api/v1/sessions/vigilancia_issste/bind-company
{"company_id": "co_1780079004578"}
```

---

## Rollback si falla smoke

1. `git checkout 5dbbf1b -- backend/` (pre-HRU)
2. `docker compose up -d --build backend`
3. Documentar blocker en issue

---

## Referencias

- Playbook: [`DEPLOY_HARDENING_PLAYBOOK.md`](../DEPLOY_HARDENING_PLAYBOOK.md) §10
- Factory reset: [`ARTIFACT_LIFECYCLE.md`](ARTIFACT_LIFECYCLE.md) §9
- SPEC: [`SPEC_EXPEDIENTE_READINESS_AND_INTEGRITY_HRU.md`](SPEC_EXPEDIENTE_READINESS_AND_INTEGRITY_HRU.md)
