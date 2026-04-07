# Prueba E2E exhaustiva (API + contrato frontend)

Esta guía define una validación **sin navegador**, equivalente a lo que consume React vía `axios`: mismos endpoints, mismos JSON. Los archivos de bases reales viven fuera del repo de aplicación, en la carpeta compartida de pruebas.

## Ubicación de fixtures (no commitear PDFs en Git)

| Rol | Archivo | Ruta base |
|-----|---------|-----------|
| Texto nativo (PDF legible) | `LA-51-GYN-051GYN025-N-8-2024 VIGILANCIA.pdf` | `C:\LicitAI_Multi_Agent\bases y convocatorias de prueba\` |
| Escaneado / imagen | `Bases licitacion OPM-001-2026.pdf` | Misma carpeta |

Ruta literal Windows (copiar en scripts):

`C:\LicitAI_Multi_Agent\bases y convocatorias de prueba\`

**Nota:** El PDF OPM es muy pesado (~121 MB). Subida + OCR/visión + LLM pueden superar **1 hora**. No lanzar dos `agents/process` a la vez contra el mismo backend si el worker es único: **ejecutar en serie** (nativo primero, escaneado después).

## Regla crítica: cuerpo JSON del `POST /agents/process`

En PowerShell, **no** uses `curl.exe ... -d '{...}'` con comillas: suele producir **HTTP 422** (`json_invalid`).

**Forma correcta:**

1. Guardar el body en un archivo UTF-8 **sin BOM**, por ejemplo `data\e2e_outputs\body_process.json`:

```json
{"session_id":"TU_SESSION_ID","company_id":null,"company_data":{"mode":"analysis_only"}}
```

2. Enviar con:

```powershell
curl.exe -s -X POST "http://127.0.0.1:8001/api/v1/agents/process" `
  -H "Content-Type: application/json" `
  --data-binary "@C:\ruta\a\body_process.json" `
  -o ".\data\e2e_outputs\process_salida.json" `
  --max-time 7200
```

Hasta que el servidor responda, **el archivo de salida puede no actualizarse** (curl escribe al finalizar). Un timeout de red sin respuesta indica que el orquestador sigue trabajando (normal en PDFs grandes).

**Alternativa (PowerShell):**

```powershell
$bodyObj = @{ session_id = "TU_SESSION_ID"; company_id = $null; company_data = @{ mode = "analysis_only" } } | ConvertTo-Json -Depth 5 -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/v1/agents/process" -Method Post -Body $bodyObj -ContentType "application/json; charset=utf-8" -TimeoutSec 7200
```

## Prerrequisitos

1. `docker compose up -d` (backend `:8001`, Postgres, Chroma, Redis).
2. Ollama en el host con el modelo configurado en `OLLAMA_MODEL` (p. ej. `llama3.1:8b`).
3. PowerShell o `curl.exe` en Windows.

## Secuencia por archivo (repetir para cada PDF)

### 1) Salud del sistema

```powershell
curl.exe -s "http://127.0.0.1:8001/api/v1/health"
```

**Criterios:** `status: ok`, `database: ok`, `llm_ollama: ok`. Anotar si `ocr_vlm` aparece `unavailable` (conocido; revisar health check del cliente OCR).

### 2) Crear sesión dedicada

Una sesión por PDF evita mezclar vectores y dictámenes.

```powershell
$name = [uri]::EscapeDataString("E2E Nativo VIGILANCIA 2026")
curl.exe -s -X POST "http://127.0.0.1:8001/api/v1/sessions/create?name=$name"
```

Guardar `session_id` del JSON.

### 3) Subida multipart

Ruta entre comillas por espacios en el nombre del archivo:

```powershell
$pdf = "C:\LicitAI_Multi_Agent\bases y convocatorias de prueba\LA-51-GYN-051GYN025-N-8-2024 VIGILANCIA.pdf"
curl.exe -s -X POST "http://127.0.0.1:8001/api/v1/upload/upload" `
  -F "file=@$pdf" `
  -F "session_id=SESSION_ID"
```

**Criterios:** `success: true`, `data.doc_id` presente.

### 4) Pipeline `analysis_only`

Usar **archivo de body** + `--data-binary @ruta` (ver sección “Regla crítica” arriba). Sustituir `SESSION_ID`:

```powershell
$json = '{"session_id":"SESSION_ID","company_id":null,"company_data":{"mode":"analysis_only"}}'
[System.IO.File]::WriteAllText(".\data\e2e_outputs\body_process.json", $json, [System.Text.UTF8Encoding]::new($false))
curl.exe -s -X POST "http://127.0.0.1:8001/api/v1/agents/process" `
  -H "Content-Type: application/json" `
  --data-binary "@.\data\e2e_outputs\body_process.json" `
  -o ".\data\e2e_outputs\process_SESSION.json" --max-time 7200
```

**Criterios:** HTTP 200 al terminar el orquestador; JSON con `status`, `data` (`analysis`, `compliance`, `economic`). Mientras el servidor procesa, la petición permanece abierta (puede tardar muchos minutos).

### 5) Dictamen en Postgres

```powershell
curl.exe -s "http://127.0.0.1:8001/api/v1/sessions/SESSION_ID/dictamen"
```

**Importante:** Tras solo API, suele responder `No hay dictamen guardado` porque el **frontend** hace `POST .../dictamen` tras procesar. Para equivalencia UI, o bien ejecutar esa misma persistencia desde un script, o validar solo el cuerpo de `process`.

### 6) Lista de documentos

```powershell
curl.exe -s "http://127.0.0.1:8001/api/v1/upload/list/SESSION_ID"
```

### 7) Logs backend (incidencias RAG, compliance, timeouts)

```powershell
docker compose logs backend --tail 200
```

## Contrato con el frontend (`processAuditResults`)

El cliente transforma `res.data.data` del `process` (y el dictamen guardado con la misma forma) con `frontend/src/utils/auditSummary.js`:

- `analysis.requisitos_filtro`
- `compliance.data` (administrativo, técnico, formatos), `compliance.summary`, `compliance.status`, `compliance.metrics.zones`
- `economic.data...`

**Verificación manual:** abrir el JSON guardado y comprobar que existen las ramas que `processAuditResults` concatena en `causales` y en `totalRequisitos` / `riesgos`.

## Matriz de aceptación mínima

| Caso | Expectativa razonable |
|------|------------------------|
| PDF nativo | Texto extraíble; SmartSearch con fragmentos > 0; analyst con contexto > umbral; compliance con ítems o zonas coherentes |
| PDF escaneado | Vision/OCR activo; tiempos mayores; posibles zonas `partial` si falla un tramo |

## Automatización

Ver `scripts/e2e-run-bases-reales.ps1` en este repositorio.
