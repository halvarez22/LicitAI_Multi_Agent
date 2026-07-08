# SPEC + Arquitectura + Plan — Descarga contextual post-generación (F5 HRU)

**Versión:** 1.0.0  
**Fecha:** 2026-07-02  
**Origen:** Feedback piloto ISSSTE vigilancia — generación desacoplada sin CTA de descarga intuitiva  
**Normativa:** [`ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](ESTANDAR_ENTERPRISE_CANONICO_HITL.md)  
**Relacionado:** [`SPEC_DECOUPLED_GENERATION_AND_CHAT_ECONOMIC_HITL.md`](SPEC_DECOUPLED_GENERATION_AND_CHAT_ECONOMIC_HITL.md) (F2–F3), [`PILOT_SIGNOFF_CHECKLIST.md`](PILOT_SIGNOFF_CHECKLIST.md), [`GUIA_PILOTO_ONPREM_HRU.md`](GUIA_PILOTO_ONPREM_HRU.md)

---

## 0. Resumen ejecutivo

Tras F2–F3 el usuario puede generar **técnica**, **económica** o **completo** por separado, pero la descarga sigue anclada al panel lejano **“Logística y Expedientes”**, con rutas internas (`1.propuesta tecnica`) y sin enlace causal con el botón que pulsó.

| ID | Requerimiento | Intención |
|----|---------------|-----------|
| **REQ-3** | CTA de descarga **contextual** bajo cada modo de generación independiente | “Generé técnica → aquí la bajo” sin conocimiento tácito de la app |
| **REQ-3b** | Resumen humano de **qué se generó** y **qué falta** por modo | Cerrar el ciclo acción → resultado → entrega |
| **REQ-3c** | Mantener panel logístico como vista avanzada | No duplicar lógica CompraNet; una sola verdad en disco |

**Principio rector (HRU):** la **misma política versionada** que define modos de generación define **alcances de descarga** y **etiquetas humanas** — cero nombres de carpeta expuestos al licitante, cero reglas por convocante en código.

---

## 1. Alineación HRU

| Pilar | Aplicación en F5 |
|-------|------------------|
| **H — Cero hardcoding** | Mapeo modo → carpetas/ sobres → labels en `delivery_scope_policy.json`; resolución vía servicio, no `if issste` en UI |
| **R — Cero regresiones** | Reutilizar `output_delivery_view`, `/downloads/file`, `/downloads/zip`; no alterar writers ni packager; tests Oracle PKG01 intactos |
| **U — Universalidad** | Misma UX para vigilancia ISSSTE, ISAPEG, limpieza, etc.; copy centralizado en `delivery_ux_messages.json` |

**HITL / procedencia:** cada archivo listado expone `provenance_ui` mínimo (`source: generation_job`, `job_id`, `generated_at` si disponible en sesión).

---

## 2. Especificaciones funcionales

### 2.1 User stories

| ID | Como… | Quiero… | Para… |
|----|--------|---------|-------|
| US-3.1 | Licitante | Tras **Generar técnica**, ver un botón **“Descargar propuesta técnica”** justo debajo | Bajar documentos sin buscar en otro panel |
| US-3.2 | Licitante comercial | Tras **Generar económica**, descargar solo cotización / sobre 3 | Entregar incrementalmente |
| US-3.3 | Usuario nuevo | Ver cuántos archivos hay listos y nombres legibles | Saber si la generación “sirvió” |
| US-3.4 | Usuario que regresa mañana | Que el botón siga visible si hay artefactos en disco | No depender del banner efímero |
| US-3.5 | Coordinador | Descargar ZIP **por alcance** (técnica / económica / completo) | Empaquetado parcial alineado a F3 |
| US-3.6 | Auditor | Ver en API qué jobs `generation_state` respaldan cada archivo | Trazabilidad operativa |

### 2.2 Comportamiento requerido

#### 2.2.1 Zona UI — “Acciones de generación”

Ubicación: bloque existente de botones (`GENERAR COMPLETO`, `TÉCNICA`, `ECONÓMICA`) en `App.jsx`.

```
┌─────────────────────────────────────┐
│  [ GENERAR COMPLETO              ]  │
│  [ TÉCNICA ]    [ ECONÓMICA      ]  │
├─────────────────────────────────────┤
│  ▼ Resultado — Propuesta técnica    │  ← visible si scope technical tiene ≥1 archivo
│     3 archivos listos               │
│  [ Descargar propuesta técnica ▼ ]  │  ← abre mini-panel / modal
├─────────────────────────────────────┤
│  ▼ Resultado — Propuesta económica  │  ← visible si scope economic tiene ≥1 archivo
│     (vacío / pendiente precios)     │
│  [ Descargar cotización ] (disabled)│
└─────────────────────────────────────┘
│  GenerationQueuePanel (existente)   │
└─────────────────────────────────────┘
```

Reglas:

1. **Proximidad:** CTA de descarga **directamente bajo** el botón del modo correspondiente (técnica → bloque técnico; económica → bloque económico; completo → bloque “Expediente completo” o reutiliza ambos + ZIP global).
2. **Visibilidad:** Mostrar bloque si `artifact_count > 0` **o** si el job del modo terminó `done`/`partial` en las últimas 24h (estado en sesión) — evita botón fantasma en sesiones vacías.
3. **Post-éxito inmediato:** Al terminar generación con `status=success|partial`, **scroll suave + highlight** al bloque del modo activo y banner de una línea: *“Listo — descarga tus archivos aquí ↓”*.
4. **No sustituir** `DeliveryPanel`: enlace secundario *“Ver logística avanzada”* hace scroll al panel derecho.

#### 2.2.2 Mini-panel de descarga (modal o drawer compacto)

Al pulsar el CTA contextual:

| Elemento | Contenido |
|----------|-----------|
| Título | Label humano del alcance (desde policy) |
| Lista | Archivos con icono por extensión, tamaño, botón ⬇ individual |
| Acción masiva | **Descargar todo (ZIP)** del alcance — max N archivos / tamaño configurable |
| Estado vacío | *“Aún no hay documentos. Si la cola muestra error, revisa arriba.”* |
| Parcial | Badge *“Expediente parcial”* si falta sobre según manifiesto F3 |

**Prohibido en UI licitante:** strings `1.propuesta tecnica`, `SOBRE_2_TECNICO`, códigos `INCOMPLETE_*`, `ECONOMIC_PRICES_*`.

#### 2.2.3 Alcances (`scope`) canónicos

| `scope` | Incluye (política, no hardcode en React) | Excluye |
|---------|------------------------------------------|---------|
| `technical` | Propuesta técnica + formatos admin generados en modo técnico/full | Económica, sobres no generados |
| `economic` | Propuesta económica + sobre 3 si existe | Técnica exclusiva de modo partial |
| `full` | Vista entrega CompraNet (`_compranet_validated`) + logística raíz | Duplicados podados por `output_delivery_view` |
| `admin_only` | Solo formatos administrativos (opcional v1.1) | Técnica pura |

La resolución de rutas en disco vive en **`delivery_scope_policy.json`** (aliases de carpetas, sobres CompraNet, extensiones permitidas).

#### 2.2.4 Sincronización con `generation_state`

| Job `done` | Scope habilitado mínimo |
|------------|-------------------------|
| `technical` | `technical` (si hay archivos en rutas policy) |
| `formats` | `technical` (admin incluido en mismo bloque UX “técnica y formatos”) |
| `economic_writer` | `economic` |
| `packager` + `delivery` | `full` (+ manifiesto) |

Si job=`done` pero disco vacío → UI **honesta**: mensaje de error recuperable + botón **Actualizar lista** (llama API).

### 2.3 Criterios de aceptación (F5)

- [ ] **CA-3.1:** Tras generación **técnica** exitosa en sesión ISSSTE (o fixture sintética), aparece CTA **“Descargar propuesta técnica”** bajo botón TÉCNICA sin scroll manual al panel derecho.
- [ ] **CA-3.2:** Lista muestra ≥1 archivo con nombre humano; descarga individual funciona vía API existente.
- [ ] **CA-3.3:** Modo **económica** sin precios → CTA deshabilitado con texto *“Completa precios en el chat para generar la cotización”* — no botón muerto sin explicación.
- [ ] **CA-3.4:** Tras F5, flujos F2 CA-1.1–1.5 siguen verdes (regresión CI).
- [ ] **CA-3.5:** Ningún label de UI contiene rutas internas de disco (test snapshot frontend o lint de copy).
- [ ] **CA-3.6:** API `/downloads/artifacts?scope=` responde igual para dos sesiones distintas con misma estructura de salida (universalidad).
- [ ] **CA-3.7:** ZIP por scope no incluye archivos de otro scope (test unitario backend).
- [ ] **CA-3.8:** Recarga de página (F5) mantiene CTAs visibles si hay artefactos en disco.

### 2.4 Fuera de alcance F5 v1

- Re diseño completo del chat económico (F1) ni mensajes `price_source` (issue aparte).
- Sustituir CompraNetPackager o reglas de nombrado SHA.
- App móvil nativa / PWA offline.
- Edición de documentos desde el modal de descarga.

---

## 3. Arquitectura

### 3.1 Diagrama de flujo

```mermaid
flowchart TB
  subgraph ui [Frontend]
    BTN[Botones Generar full/technical/economic]
    GDA[GenerationDownloadActions]
    MOD[Mini-panel descarga]
    ADV[DeliveryPanel avanzado]
  end

  subgraph api [Backend API v1]
    ART[GET /downloads/artifacts]
    FILE[GET /downloads/file]
    SZIP[GET /downloads/scope-zip]
    LIST[GET /downloads/list legacy]
  end

  subgraph svc [Servicios HRU]
    POL[delivery_scope_policy.json]
    DSR[delivery_scope_resolver.py]
    ODV[output_delivery_view.py]
    GMP[generation_mode_policy.json]
  end

  subgraph disk [/data/outputs/session_id]
    TECH[1.propuesta tecnica]
    ADM[3.documentos administrativos]
    ECO[2.propuesta_economica]
    CN[_compranet_validated]
  end

  BTN -->|generation_mode| ORCH[Orchestrator F2]
  ORCH --> disk
  BTN --> GDA
  GDA -->|scope| ART
  ART --> DSR
  DSR --> POL
  DSR --> ODV
  DSR --> GMP
  DSR --> disk
  MOD --> FILE
  MOD --> SZIP
  GDA -->|link secundario| ADV
  ADV --> LIST
```

### 3.2 Componentes nuevos / modificados

| Capa | Artefacto | Responsabilidad |
|------|-----------|-----------------|
| **Contrato** | `backend/app/contracts/delivery_scope_policy.json` | Alcances, labels ES, carpetas, sobres, extensiones |
| **Contrato** | `backend/app/contracts/delivery_ux_messages.json` | Copy UI: títulos, vacío, parcial, errores |
| **Servicio** | `backend/app/services/delivery_scope_resolver.py` | `list_artifacts(session_id, scope)` → lista canónica |
| **Servicio** | `backend/app/services/delivery_scope_policy.py` | Loader + validación schema (patrón `generation_mode_policy`) |
| **API** | `GET /downloads/artifacts` | Query: `session_id`, `scope`; respuesta JSON estable |
| **API** | `GET /downloads/scope-zip` | ZIP filtrado por scope (opcional v1; puede ser F5.2) |
| **Frontend** | `GenerationDownloadActions.jsx` | Bloques contextual bajo cada modo |
| **Frontend** | `ArtifactDownloadModal.jsx` | Lista + descargas |
| **Frontend** | `App.jsx` | Integración post-`triggerGeneration`, refresh token |
| **Tests** | `test_delivery_scope_resolver.py`, `test_downloads_artifacts_route.py` | HRU regresión |
| **Smoke** | `scripts/smoke_contextual_download_hru.py` | E2E API + conteo archivos post-generación técnica |

### 3.3 Contrato API — `GET /downloads/artifacts`

**Request**

```
GET /api/v1/downloads/artifacts?session_id={id}&scope=technical|economic|full
```

**Response 200**

```json
{
  "success": true,
  "data": {
    "scope": "technical",
    "scope_label": "Propuesta técnica y formatos administrativos",
    "ready": true,
    "artifact_count": 3,
    "generation_jobs": ["technical", "formats"],
    "packaging_coverage_status": null,
    "artifacts": [
      {
        "id": "sha256:abc…",
        "filename": "Propuesta_Tecnica_Vigilancia.docx",
        "display_name": "Propuesta técnica",
        "relative_path": "1.propuesta tecnica/Propuesta_Tecnica_Vigilancia.docx",
        "size_bytes": 128400,
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "download_url": "/api/v1/downloads/file?session_id=…&path=…",
        "provenance_ui": {
          "source": "generation_job",
          "source_label": "Generación técnica",
          "job_id": "technical",
          "confidence": 1.0
        }
      }
    ],
    "actions": {
      "download_all_zip_url": "/api/v1/downloads/scope-zip?session_id=…&scope=technical",
      "refresh_hint": "Actualizar si acabas de generar"
    },
    "empty_reason": null
  }
}
```

**`ready: false`** — incluir `empty_reason` con clave estable (`no_files_on_disk`, `prices_required`, `generation_not_run`, `job_failed`) mapeada a copy en frontend vía `delivery_ux_messages.json`.

### 3.4 Política `delivery_scope_policy.json` (borrador)

```json
{
  "policy_version": "1.0.0",
  "scopes": {
    "technical": {
      "label": "Propuesta técnica y formatos administrativos",
      "short_label": "Propuesta técnica",
      "generation_jobs_hint": ["technical", "formats"],
      "include_directories": [
        "1.propuesta tecnica",
        "1.propuesta_tecnica",
        "3.documentos administrativos"
      ],
      "include_compranet_sobres": ["SobreComplementaria", "SobreTecnica"],
      "cta_download": "Descargar propuesta técnica",
      "cta_download_all": "Descargar todo (técnica y admin)"
    },
    "economic": {
      "label": "Propuesta económica",
      "short_label": "Cotización económica",
      "generation_jobs_hint": ["economic_writer"],
      "include_directories": ["2.propuesta_economica", "2.propuesta economica"],
      "include_compranet_sobres": ["SobreEconomica"],
      "cta_download": "Descargar cotización económica",
      "cta_download_all": "Descargar todo (económico)"
    },
    "full": {
      "label": "Expediente completo",
      "prefer_compranet_validated": true,
      "include_root_logistics": ["LOGISTICA_Y_GUIA_DE_ENTREGA.pdf", "GUIA_DE_ARMADO_Y_CHECKLIST.docx"],
      "cta_download": "Descargar expediente",
      "cta_download_all": "Descargar expediente (ZIP)"
    }
  },
  "allowed_extensions": [".doc", ".docx", ".pdf", ".xlsx", ".xls"],
  "max_artifacts_list": 100
}
```

> **Nota HRU:** los nombres de directorio solo existen en JSON; React consume `scope_label` y `display_name`.

### 3.5 Resolución de archivos (algoritmo)

1. `resolve_outputs_root(session_id)` — existente en `downloads.py`.
2. Cargar `generation_state` de sesión (jobs + `generation_mode` último).
3. Para cada ruta en `include_directories` / sobres CompraNet del scope:
   - Enumerar archivos con extensión permitida.
   - Deduplicar por SHA-256 (reutilizar lógica `output_delivery_view`).
4. Si `prefer_compranet_validated` y existe manifiesto → priorizar árbol validado (scope `full`).
5. Enriquecer con `provenance_ui` según job correlacionado.
6. Orden estable: admin → técnica → económica; luego alfabético.

### 3.6 Frontend — estado y eventos

| Estado React | Fuente |
|--------------|--------|
| `artifactsByScope.technical` | `GET /downloads/artifacts?scope=technical` |
| `artifactsByScope.economic` | `scope=economic` |
| `lastGenerationMode` | ya existe `activeGenerationMode` |
| Refresh | `deliveryRefreshToken` incrementado post-generación + al abrir modal |

**Eventos**

- `onGenerationComplete(mode, orchestratorStatus)` → fetch artifacts del scope + scroll a `#generation-download-{mode}`.
- No polling agresivo: refresh manual + un retry a los 3s post-generación.

### 3.7 Cascada de precedencia (entregables)

```
Archivos en _compranet_validated (si packager corrió)
  > Archivos en carpetas de generación del scope
  > (nunca) mezclar scope economic en ZIP technical
```

---

## 4. Plan de implementación

### 4.1 Fase F5 — Descarga contextual (1 sprint + QA)

| ID | Tarea | Archivos / área | DoD |
|----|-------|-----------------|-----|
| **F5.1** | Policy JSON + loader | `delivery_scope_policy.json`, `delivery_scope_policy.py` | Schema validado; tests loader |
| **F5.2** | Resolver servicio | `delivery_scope_resolver.py` | CA-3.6, CA-3.7 unitarios |
| **F5.3** | Copy UX centralizado | `delivery_ux_messages.json` + helper Python opcional | Sin strings dispersos en JSX |
| **F5.4** | API `GET /downloads/artifacts` | `routes/downloads.py` | OpenAPI + tests ruta |
| **F5.5** | API `GET /downloads/scope-zip` (opcional v1) | `routes/downloads.py` | ZIP scope-limited; límite tamaño |
| **F5.6** | Componente `GenerationDownloadActions` | `frontend/src/components/` | CA-3.1, CA-3.5 |
| **F5.7** | Modal `ArtifactDownloadModal` | frontend | Descarga individual + zip |
| **F5.8** | Integración `App.jsx` | post `triggerGeneration`, layout botones | CA-3.8, banner post-éxito |
| **F5.9** | Enlace “Logística avanzada” | scroll a `DeliveryPanel` | No regresión panel existente |
| **F5.10** | Tests regresión F2 | `test_orchestrator_decoupled_generation.py` + nuevo oracle | CI verde |
| **F5.11** | Smoke HRU | `scripts/smoke_contextual_download_hru.py` | Técnica → artifacts ≥1 |
| **F5.12** | Docs piloto | `PILOT_SIGNOFF_CHECKLIST.md`, `GUIA_PILOTO_ONPREM_HRU.md` | Ítem descarga contextual |

**Duración estimada:** 1 sprint (2 semanas) incluyendo prueba manual ISSSTE.

### 4.2 Orden de ejecución recomendado

```
F5.1 → F5.2 → F5.4 → F5.10 (backend cerrado)
     → F5.3 → F5.6 → F5.7 → F5.8 → F5.9 (frontend)
     → F5.11 → F5.12 (cierre piloto)
     → F5.5 si hay tiempo en sprint (ZIP por scope; si no, v1.1)
```

### 4.3 Feature flags

| Variable | Default | Efecto |
|----------|---------|--------|
| `LICITAI_CONTEXTUAL_DOWNLOAD_ENABLED` | `true` | Muestra bloques F5; `false` = solo DeliveryPanel legacy |

Sin flag por licitación. Sin flag por convocante.

### 4.4 Checklist sign-off ampliado (añadir a piloto)

- [ ] Tras **Generar técnica**, descarga visible **sin** abrir panel Logística.
- [ ] Tras **Generar económica** (con precios), descarga de cotización en el mismo bloque.
- [ ] Usuario de prueba **sin capacitación** encuentra descarga en ≤2 clics post-generación.
- [ ] Nombres visibles sin rutas técnicas de disco.

---

## 5. Riesgos y mitigación

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Modo técnico sin packager → no hay SOBRE_* | Usuario espera sobre CompraNet | Copy: *“Archivos de trabajo; empaquetado CompraNet al generar completo”*; listar carpetas de generación |
| Duplicados técnica vs `_compranet_validated` | ZIP inflado | SHA dedupe en resolver; prefer validated en `full` |
| Sesión con carpeta legado por `name` vs `session_id` | Lista vacía | Reutilizar `resolve_outputs_root` |
| Scope economic sin snapshot | CTA confuso | `empty_reason=prices_required` + disabled con tooltip |
| Sobrecarga UI (3 bloques + cola + chat) | Ruido visual | Colapsar bloques vacíos; solo expandir modo activo + modos con archivos |

---

## 6. Métricas de éxito (30 días post-F5)

| Métrica | Objetivo |
|---------|----------|
| Tiempo mediano hasta primera descarga post-generación | < 30 s (observabilidad frontend opcional) |
| Tickets “¿dónde descargo?” en piloto | −80% vs baseline ISSSTE |
| Regresiones CI F2/F3 | 0 |
| Satisfacción UX piloto (encuesta 1–5) | ≥ 4 en ítem “facilidad de descarga” |

---

## 7. Issues relacionados (no F5, backlog)

| Issue | Descripción |
|-------|-------------|
| **UX-ECO-01** | Mensajes contradictorios `price_source` vs “solo el número” en chat |
| **UX-INTAKE-01** | Panel Intake `Bloqueantes: 0` no refleja bloqueo económico |
| **UX-JUNTA-01** | Preguntas junta mezcladas en hilo de chat / contaminación temática |

F5 no bloquea estos; puede implementarse en paralelo.

---

## 8. Referencias de código actual (punto de partida)

| Área | Ruta |
|------|------|
| Botones generación | `frontend/src/App.jsx` (`triggerGeneration`, ~L2120) |
| Panel logística | `frontend/src/components/DeliveryPanel.jsx` |
| Modos generación | `frontend/src/generationModeUi.js`, `generation_mode_policy.json` |
| API descargas | `backend/app/api/v1/routes/downloads.py` |
| Vista entrega | `backend/app/services/output_delivery_view.py` |
| Cola generación | `backend/app/services/generation_queue_controller.py` |

---

**Siguiente paso acordado:** revisión de este SPEC → implementación F5.1–F5.8 en branch dedicado → prueba manual ISSSTE vigilancia → sign-off checklist.
