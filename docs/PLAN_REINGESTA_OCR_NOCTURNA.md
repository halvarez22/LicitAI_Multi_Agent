# Plan de re-ingesta OCR nocturna (LicitAI)

**Objetivo:** Reconstruir `extracted_text` + vectores Chroma con calidad forense, empezando por `opm_municipio_madera` (bases OPM-001-2026), sin bloquear el día y sin repetir el error del prompt largo.

**¿Es correcto hacerlo de noche?** **Sí.** La ingesta híbrida llama a `glm-ocr` **página por página** (~30–90 s/página en GPU). Un PDF de 53 hojas puede tardar **45–120 minutos** solo en OCR, más indexación vectorial. De día compite con chat, analista y compliance por VRAM/Ollama.

**Advertencia crítica:** Si re-ingieres **sin** corregir el prompt de visión, repetirás páginas contaminadas con *«ANALIZAR Y TRANSCRIBIR…»* (informe `backend/scratch/reingesta_ocr_opm_report.json`). La Fase 0 es **obligatoria** antes de la corrida masiva.

---

## Resumen de fases

| Fase | Cuándo | Duración estimada |
|------|--------|-------------------|
| **0** Ajuste prompt + gate de calidad | Tarde (antes de dormir) | 30–60 min dev + 1 PDF prueba |
| **1** Preflight infra | Inicio de la noche | 5 min |
| **2** Re-ingesta bases OPM (1 PDF) | Noche | 45–120 min |
| **3** Auditoría automática de calidad | Tras Fase 2 | 5–10 min |
| **4** Refresco downstream (calendario, junta, opcional analista) | Tras auditoría OK | 20–60 min |
| **5** Otras sesiones / PDFs | Otra noche si aplica | N × tiempo por PDF |

---

## Fase 0 — Corregir insumo (obligatorio)

### Problema confirmado

- Modelo disponible: **`glm-ocr:latest`** en Ollama.
- Fallo: prompt forense largo en `VisionExtractorAgent.extract_page_vision` → el modelo **devuelve las instrucciones**.
- Prompt corto tipo *Text Recognition* → **~2k caracteres útiles** en las mismas páginas (p. 3, 15, 24).

### Cambio mínimo acordado (antes de la noche)

1. **Prompt de producción** alineado al uso nativo de GLM-OCR (corto, en inglés o bilingüe breve), sin repetir el encabezado que luego se indexa como texto.
2. **Gate por página** tras VLM: si `looks_like_low_signal_ocr(text)` **o** el texto contiene el prefijo del prompt de sistema → **reintento 1 vez** con prompt corto; si sigue mal → marcar `quality_flags: ["vlm_prompt_echo"]` y no persistir solo el eco.
3. **Persistir** en `content.pages[]` el campo `method` y `quality_flags` por página (hoy solo se guarda `extracted_text`; impide auditar después).

### Prueba rápida (10 min, 2 páginas)

```bash
docker compose up -d --build backend
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 \
  python scripts/reingesta_ocr_diagnostico.py \
  --session opm_municipio_madera --pages 3,15 --out-dir /app/scratch
```

**Criterio de salida Fase 0:** En el informe, `reingesta_vlm_forensic_prompt` (o el nuevo prompt de prod) clasificado **OK** y ≥1.500 caracteres en pág. 3 o 15, sin eco del prompt al inicio.

---

## Fase 1 — Preflight (inicio de noche)

### 1.1 Servicios

```bash
docker compose up -d database vector-db queue-redis backend
docker compose ps
docker compose logs backend --tail 30
```

### 1.2 Ollama en el host

```bash
# En el host (fuera del contenedor)
ollama list | findstr glm
curl http://localhost:11434/api/tags
```

Debe aparecer **`glm-ocr:latest`**. No levantar cargas pesadas de chat durante la ingesta.

### 1.3 VRAM y concurrencia

- **Un solo PDF a la vez.**
- **No** lanzar `/agents/process` (orquestador completo) en paralelo.
- `workers=1` en backend (ya está en compose) — mantener así.

### 1.4 Snapshot de rollback (opcional, 2 min)

```bash
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 \
  python scripts/monitor_session_ingestion.py \
  --session opm_municipio_madera --json /app/scratch/pre_reingest_opm.json
```

Guarda copia del JSON en `backend/scratch/` del repo si montas volumen.

---

## Fase 2 — Re-ingesta masiva del PDF de bases (OPM)

### Documento objetivo

| Campo | Valor |
|-------|--------|
| Sesión | `opm_municipio_madera` |
| Archivo | `Bases licitacion OPM-001-2026.pdf` |
| doc_id | `39049ae9-ee20-438e-bf0d-d40f189e2de1` (verificar con monitor si cambió) |
| Páginas | 53 |
| Ruta disco | `/data/uploads/..._bases_licitacion_opm-001-2026.pdf` |

### Opción A — API `force=true` (recomendada si UI o curl)

```bash
curl -X POST "http://localhost:8001/api/v1/upload/process/39049ae9-ee20-438e-bf0d-d40f189e2de1?force=true" \
  -F "session_id=opm_municipio_madera"
```

El endpoint borra vectores del doc y vuelve a OCR + indexación atómica.

### Opción B — Script en contenedor (sin timeout HTTP)

Crear/usar un script que replique `repair_failed_session_docs.py` pero para **PDF ANALYZED** con `--force`. Hasta que exista en repo, bloque Python inline:

```bash
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 python -c "
import asyncio, json, os
from datetime import datetime, timezone

SESSION = 'opm_municipio_madera'
DOC_ID = '39049ae9-ee20-438e-bf0d-d40f189e2de1'  # verificar antes

async def main():
    from app.memory.factory import MemoryAdapterFactory
    from app.services.document_ingestion_router import DocumentIngestionRouter
    from app.services.document_vector_index import index_pages_atomic
    from app.services.vector_service import VectorDbServiceClient

    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    doc = await mem.get_document(DOC_ID)
    c = doc['content']
    fn, fp = c['filename'], c['file_path']
    print(f'[{datetime.now(timezone.utc).isoformat()}] Inicio re-ingesta: {fn}')

    vc = VectorDbServiceClient()
    vc.delete_by_doc_id(SESSION, DOC_ID)

    router = DocumentIngestionRouter()
    ocr = await router.ingest(fp, fn, SESSION, DOC_ID, memory=mem)
    if not ocr.get('success'):
        print('FALLO', ocr.get('error'))
        await mem.disconnect()
        return

    pages = ocr.get('pages') or []
    chunks = index_pages_atomic(SESSION, DOC_ID, fn, pages, vc)
    c['extracted_text'] = ocr.get('extracted_text', '')
    c['total_pages'] = ocr.get('total_pages', len(pages))
    c['status'] = 'ANALYZED'
    c['reingested_at'] = datetime.now(timezone.utc).isoformat()
    await mem.save_document(DOC_ID, SESSION, c, {'status': 'ANALYZED', 'filename': fn})
    await mem.disconnect()
    print(json.dumps({
        'ok': True, 'chunks': chunks, 'chars': len(c['extracted_text']),
        'pages': len(pages)
    }, indent=2))

asyncio.run(main())
" 2>&1 | tee /app/scratch/reingest_opm_$(date +%Y%m%d_%H%M).log
```

**Monitoreo en otra terminal:**

```bash
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 \
  python scripts/monitor_session_ingestion.py --session opm_municipio_madera --watch 30
```

Busca subida de `text_len` (objetivo: claramente por encima del valor previo si el corpus mejora) y `chunk_total` estable.

---

## Fase 3 — Auditoría de calidad (post-ingesta)

### 3.1 Métricas globales

```bash
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 \
  python scripts/monitor_session_ingestion.py \
  --session opm_municipio_madera --json /app/scratch/post_reingest_opm.json
```

### 3.2 Muestreo OCR (páginas problema + control)

```bash
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 \
  python scripts/reingesta_ocr_diagnostico.py \
  --session opm_municipio_madera --pages 3,15,16,24,7,8 \
  --out-dir /app/scratch/post_run
```

**Criterios de aceptación (mínimo):**

| Métrica | Umbral |
|---------|--------|
| Páginas con eco de prompt | **0** en muestra 3,15,16 |
| Pág. 7–8 (calendario) | Texto con «26 de enero», «30 de enero» |
| Pág. 24 (fallo) | Texto narrativo de fallo, no solo instrucciones |
| `text_len` total bases | Sensiblemente mayor que pre-reingesta si antes había ~34% páginas malas |

### 3.3 Script rápido de conteo (todas las páginas)

```bash
docker exec -w /app -e PYTHONPATH=/app licitaciones-ai-backend-1 python -c "
import asyncio, re
PROMPT='ANALIZAR Y TRANSCRIBIR'
async def main():
    from app.memory.factory import MemoryAdapterFactory
    mem = MemoryAdapterFactory.create_adapter()
    await mem.connect()
    for d in await mem.get_documents('opm_municipio_madera') or []:
        c = d.get('content') or {}
        if 'bases' not in str(c.get('filename','')).lower(): continue
        parts = re.split(r'--- PÁGINA (\d+) ---', c.get('extracted_text') or '')
        bad = ok = 0
        for i in range(1, len(parts), 2):
            body = (parts[i+1] if i+1 < len(parts) else '').strip()
            if PROMPT in body[:150] and len(body) < 700: bad += 1
            else: ok += 1
        print(f'OK={ok} contaminadas={bad} total_pag={(ok+bad)} chars={len(c.get(\"extracted_text\") or \"\")}')
    await mem.disconnect()
asyncio.run(main())
"
```

Objetivo: **contaminadas → 0** (o ≤2 si son páginas en blanco escaneadas).

---

## Fase 4 — Refresco downstream (solo si Fase 3 OK)

Orden recomendado (evita usar corpus viejo):

1. **Calendario / checklist**
   - Abrir UI calendario o `GET /api/v1/sessions/opm_municipio_madera/submission-checklist`
   - Dispara `ensure_session_cronograma_and_checklist` (enriquecimiento desde corpus).

2. **Junta de aclaraciones**
   - `GET .../junta-aclaraciones-questions?refresh=true`

3. **Mini dictamen anexos** (si aplica)
   - `GET .../mini-dictamen-anexos?refresh=true`

4. **Analista completo** (opcional, **otra ventana** o al día siguiente)
   - Re-ejecutar etapa `analysis` vía orquestador — **más 30–90 min** de LLM.
   - No mezclar con Fase 2 en la misma ventana de GPU.

---

## Fase 5 — Otras sesiones (cola)

Repetir Fase 2–4 por cada PDF de bases/convocatoria:

| Prioridad | Sesión / notas |
|-----------|----------------|
| P0 | `opm_municipio_madera` — bases |
| P1 | Sesiones de regresión Oracle / vigilancia documentadas en `CLAUDE.md` |
| P2 | Resto de sesiones con `text_len` bajo o muchas páginas «prompt only» |

**No** usar `repair_failed_session_docs.py` para PDFs ya `ANALYZED`; ese script solo marca `ERROR` / `.doc` pendientes.

---

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|--------|------------|
| Correr sin Fase 0 | Desperdicias la noche; repetirás contaminación |
| Timeout HTTP en `/process` | Usar Opción B (script en contenedor) |
| Ollama caído a mitad | Preflight; reiniciar Ollama y reanudar solo ese doc (`force=true`) |
| Páginas vacías escaneadas | Gate marca flag; revisión manual HITL |
| Mezclar orquestador + OCR | Secuencia estricta: primero OCR, luego agentes |

---

## Checklist nocturno (imprimible)

```
[ ] Fase 0 aplicada y prueba pág. 3/15 OK
[ ] ollama list → glm-ocr:latest
[ ] monitor pre_reingest guardado
[ ] Nadie usando chat/agentes pesados
[ ] Re-ingesta bases OPM iniciada (log en scratch)
[ ] monitor --watch hasta text_len estable
[ ] reingesta_ocr_diagnostico post_run OK
[ ] conteo contaminadas = 0
[ ] submission-checklist + junta refresh
[ ] (opcional) analista — mañana
```

---

## Artefactos de referencia

| Archivo | Contenido |
|---------|-----------|
| `backend/scratch/reingesta_ocr_opm_report.md` | Diagnóstico previo (prompt largo vs corto) |
| `backend/scripts/reingesta_ocr_diagnostico.py` | Re-muestreo por páginas |
| `backend/scripts/monitor_session_ingestion.py` | Estado Postgres + Chroma |
| `docs/Tunning_Perfecto_Extraccion.md` | Diseño original GLM-OCR (microservicio; hoy vía Ollama) |

---

## Respuesta directa

**Sí, es correcto ejecutar la re-ingesta por la noche:** es I/O y GPU intensiva, serial por página, y no debe competir con el resto del pipeline.

**No es correcto** lanzar la re-ingesta masiva **sin** la Fase 0: con el código actual volverías a persistir páginas basura en ~⅓ del documento.

**Orden ganador:** Fase 0 (tarde) → Fase 2 de noche → Fase 3 al despertar → Fase 4 si auditoría pasa → analista cuando tengas GPU libre.
