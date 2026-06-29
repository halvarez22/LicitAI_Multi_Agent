# Requisitos — Curación del Dictamen Forense (vista licitante)

## Introducción

El **Dictamen Forense** es el primer panel que revisa el usuario tras **Analizar bases**. Hoy expone el inventario crudo del `ComplianceAgent` y un contador global (`REQUISITOS (TOTAL)`) que incluye narrativa del convocante, ítems `informativo` y ruido procedimental. Esto contradice la promesa de producto de **extracción garantizada como materia prima** y genera desconfianza cuando aparece `COMPLETADO CON INCIDENCIAS`.

Esta feature **no elimina** el archivo forense interno; **curar** lo que ve el licitante y **separar semánticamente** la salud de ingesta de la salud de auditoría LLM.

Alineación: [`docs/ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](../../../docs/ESTANDAR_ENTERPRISE_CANONICO_HITL.md) — verdad canónica, mensajes UX centralizados, procedencia visible.

## Glosario

- **Extracción / ingesta:** OCR, PDF nativo, indexación Chroma, persistencia `extracted_text` en documento. Capa 1.
- **Auditoría forense:** `ComplianceAgent` map-reduce por zonas, validación `snip_match_pct`, bloques LLM. Capa 2.
- **Ítem accionable (licitante):** Obligación, entregable, dato o riesgo que el **participante** debe cumplir, generar o presentar.
- **Ítem de archivo:** Informativo, narrativa del convocante, preámbulo contractual, ruido procedimental sin acción del licitante.
- **Vista default:** Lo que ve el usuario sin toggles — solo accionables + riesgos + hallazgos de bases relevantes.
- **Vista archivo completo:** Volcado forense actual (opt-in) para legal/ops.
- **dictamen_curated_v1:** Bloque canónico persistido en sesión con listas separadas y estadísticas de curación.
- **extraction_health:** Estado agregado de capa 1 por sesión.
- **forensic_audit_health:** Estado agregado de capa 2 (zonas, match %, bloques vacíos).
- **curation_reason:** Código estable del motivo de exclusión de vista default (`informativo`, `convocante_narrative`, `procedural_noise`, etc.).
- **audience:** `licitante` | `convocante` | `neutral` — sujeto obligado en el texto del requisito.

## Requisitos funcionales

### R1 — Curación canónica post-compliance

**THE** sistema **SHALL** producir `dictamen_curated_v1` tras `stage_completed:compliance` (o al construir respuesta de análisis para UI).

**THE** bloque **SHALL** incluir:

- `schema_version`: `"dictamen_curated_v1"`
- `actionable_items[]` — ítems para vista default
- `archival_items[]` — ítems excluidos de default con `curation_reason`
- `stats`: conteos por bucket y por razón de exclusión
- `provenance`: `source_compliance_total`, `filter_pipeline_version`

**THE** curación **SHALL** reutilizar funciones de [`document_deliverable_filter.py`](../../../backend/app/services/document_deliverable_filter.py) donde aplique.

### R2 — Definición de ítem accionable

**AN** ítem **SHALL** incluirse en `actionable_items` si cumple al menos una:

1. `tipo_accion` ∈ `{generar, presentar_fisico, requiere_datos_licitante}`
2. `category` ∈ hallazgos de bases con impacto participación: `bases_filtro`, `risk` con `isRisk`, `economic_gap_context` bloqueante
3. `is_knockout` o equivalente en brechas Go/No-Go cuando se integren al dictamen

**AN** ítem **SHALL** excluirse de `actionable_items` si:

1. `tipo_accion === informativo` (salvo política explícita de riesgo)
2. `is_convocante_narrative(texto)` es true
3. `is_procedural_noise_not_deliverable()` es true y no es causal de desechamiento para el licitante
4. El sujeto obligado es claramente la contratante/dependencia (post-proceso `audience === convocante`)

### R3 — Vista UI default del Dictamen Forense

**THE** panel Dictamen Forense **SHALL** mostrar por defecto solo `actionable_items` (y hallazgos de bases ya filtrados según R2).

**THE** contador principal **SHALL** renombrarse a **OBLIGACIONES DETECTADAS** (o equivalente i18n) y reflejar `stats.actionable_count`, no el total crudo.

**THE** UI **SHALL** ofrecer toggle **"Ver archivo forense completo (N)"** que restaura el volcado actual para auditoría.

### R4 — Salud dual (extracción vs auditoría)

**THE** dictamen **SHALL** exponer dos indicadores independientes:

| Indicador | Fuente | Estados |
|-----------|--------|---------|
| `extraction_health` | Documentos `ANALYZED`, chars, chunks Chroma, errores ingesta | `ok` \| `degraded` \| `failed` |
| `forensic_audit_health` | `compliance.status`, `audit_summary.zones` | `ok` \| `partial` \| `failed` |

**THE** mensaje global **SHALL NOT** implicar fallo de lectura de PDF cuando `extraction_health === ok` y `forensic_audit_health === partial`.

**THE** copy UX **SHALL** centralizarse (backend `compliance_message` enriquecido o `dictamen_ux_messages.py`).

### R5 — Export PDF

**THE** export default **SHALL** incluir solo accionables + resumen de salud dual.

**IF** el usuario activó vista archivo completo, **THEN** el PDF **MAY** incluir anexo de ítems archivados con `curation_reason`.

### R6 — Persistencia y API

**THE** `dictamen_curated_v1` **SHALL** persistirse en `session_state` bajo clave versionada.

**THE** endpoint de resultados de análisis **SHALL** incluir `dictamen_curated` sin romper contrato existente de `results.compliance`.

### R7 — Mejora en origen (ComplianceAgent) — fase 3

**THE** prompt de extracción por bloque **SHALL** instruir: no extraer como requisito del licitante narrativa de facultades del convocante.

**THE** post-proceso `_reduce_zone_items` **SHALL** estampar `audience` y forzar `informativo` + `convocante_narrative` cuando aplique heurística determinista.

**THE** must-have matrix **SHALL NOT** promover ítems con `audience === convocante` a `generar`.

### R8 — Resiliencia bloques LLM (fase 4)

**WHEN** `empty_llm_response` en bloques de una zona, **THE** sistema **SHALL** registrar `block_events` y ofrecer mensaje UX con zona y números de bloque.

**THE** re-ejecución selectiva de bloques fallidos **MAY** implementarse como job de mantenimiento (`session_maintenance_job_service` patrón).

### R9 — Política de despliegue

**THE** variable `DICTAMEN_VIEW_MODE` **SHALL** aceptar:

- `licitante` (default) — vista curada
- `forense_completo` — comportamiento legacy para legal/ops

## Requisitos no funcionales

### NFR1 — Compatibilidad

- No romper `filter_compliance_for_generation`, `document_candidate_list_service`, Oracle exports.
- Paridad 1:1 `audit_processor.py` ↔ `auditSummary.js` para campos nuevos.

### NFR2 — Trazabilidad

- Cada ítem archivado: `curation_reason` estable (enum documentado).
- Logs structlog: `dictamen_curation_applied` con conteos.

### NFR3 — Tests

- Fixture con frase "Directora General de Obra Pública… facultad" → no en actionable.
- Fixture con "El licitante deberá declarar…" → sí en actionable.
- Test salud dual: extracción ok + compliance partial → mensajes distintos.

### NFR4 — Rendimiento

- Curación determinista O(n) sobre lista compliance; sin LLM adicional en hot path.

## Criterios de aceptación (UAT)

1. Usuario abre dictamen tras análisis obra municipal: contador principal < 50% del total legacy.
2. No aparece en default narrativa de Directora General / contratante.
3. Badge "Lectura de bases" verde si PDF procesado correctamente.
4. Badge "Auditoría forense" puede ser amarillo sin mensaje de "no se leyó el PDF".
5. Toggle archivo completo muestra ~369 ítems legacy equivalentes.
6. Export PDF default ≤ páginas accionables + 1 resumen.

## Casos de prueba de regresión (referencia)

| ID | Entrada | Esperado vista default |
|----|---------|------------------------|
| TC01 | Ítem `tipo_accion: informativo` | Archivo, no default |
| TC02 | "La Contratante es una Institución…" | Archivo (`convocante_narrative`) |
| TC03 | "El licitante deberá presentar…" | Default |
| TC04 | Causal desechamiento `isRisk` | Default |
| TC05 | Doc UPLOADED sin ANALYZED | `extraction_health: failed` |
