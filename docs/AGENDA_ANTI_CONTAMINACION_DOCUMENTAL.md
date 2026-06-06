# Agenda — Calidad documental y anti-contaminación (universal)

**Estado:** IMPLEMENTADO en código (2026-06-03) — P0/P1 núcleo + tests; P2.3 procedencia UI en metadatos de trazabilidad parcial.  
**Origen:** Inspección visual UNAQ + análisis forense externo + escaneos automáticos en `unaq-2026_paneles_solares`.  
**Normativa:** [`ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](ESTANDAR_ENTERPRISE_CANONICO_HITL.md) (verdad canónica, gate con `error_type` estable, HITL transaccional, cascada de precedencia, procedencia visible).

**Compromiso:** Cero hardcode por licitación (no fijar UNAQ, 001-IR, fechas ni textos de comité). Toda regla debe derivar de **bases/RAG**, **cronograma**, **master_profile** y **políticas versionadas**.

---

## Hallazgos confirmados en la corrida actual (evidencia)

| ID | Contaminación | ¿Confirmado? | Evidencia breve |
|----|---------------|--------------|-----------------|
| C1 | Rechazo LLM en anexo legal (Anexo X) | **Sí** | Texto `Lo siento… no puedo generar contenido legal` en DOCX entregado. |
| C2 | Lenguaje post-adjudicación (Anexo IX, XII) | **Sí** | `hemos sido seleccionados`, `como proveedores`, `proveedor adjudicado`. |
| C3 | Fecha = `datetime.now()` del servidor | **Sí (arquitectura)** | `FormatsAgent` usa `datetime.now()` para `doc_metadata["fecha"]`; corrida en junio → fechas junio 2026 vs recepción abril en bases. |
| C4 | Perspectiva evaluador en APU (`SobreEconomica_02`) | **Por validar en UI** | Reportado en inspección; requiere lectura literal del DOCX (patrones: `criterios de evaluación`, `evaluar la propuesta`). |
| C5 | Residuo otra licitación (“luminarias”) | **No en texto** | Escaneo sin `luminaria`/`ISAPEG`; riesgo es **plantilla genérica** y **RAG cruzado**, no string residual. |

**Nota:** La generación puede terminar en `FINAL_OK` y aun así ser **descalificable** ante comité — el gate actual no cubre contaminación jurídica/semántica.

---

## P0 — Bloqueantes de descalificación (implementar primero)

### P0.1 — Gate `llm_refusal_detected` (anti-bloqueo IA)

- **Qué:** Detectar en DOCX/texto: `lo siento`, `no puedo generar`, `como asistente`, etc.
- **Dónde:** `document_fill_quality_gate.py` (+ registro en `validation_mapping.json`).
- **Comportamiento:** `severity=block` en `enforce`; mensaje UX: reintento con ruta legal autorizada; **no** entregar en `_compranet_validated`.
- **No hardcode:** lista de patrones en política versionada, no por sesión.

### P0.2 — Gate `adjudication_language_in_proposal_stage`

- **Qué:** Patrones universales: `seleccionados como proveedor`, `proveedor adjudicado`, `hemos sido seleccionados`, etc.
- **Excepción:** frases condicionales válidas: `en caso de resultar adjudicado` (whitelist).
- **Etapas:** `formats`, `economic_writer` (no solo prompt).

### P0.3 — Gate `evaluator_perspective_detected`

- **Qué:** Patrones: `criterios de evaluación`, `el comité evaluará`, `objetivo evaluar la propuesta`, `dictamen del comité`.
- **Alcance:** Prioridad en documentos clasificados como APU / propuesta económica / análisis de precios (por `tipo`, `template_id`, nombre normalizado — no por UNAQ).

### P0.4 — Fecha de documento canónica (`document_date_resolver`)

- **Qué:** Sustituir `datetime.now()` en writers por fecha derivada de:
  1. Override usuario (HITL),
  2. `cronograma.presentacion_proposiciones` / fechas críticas normalizadas,
  3. Regla: **N días hábiles antes** del hito (config `DOCUMENT_DATE_OFFSET_BUSINESS_DAYS`, default 1–3).
- **Gate adicional:** `document_date_after_submission_deadline` si fecha materializada > hito recepción/apertura.
- **Fuente:** Reutilizar `cronograma_enrichment_service` / salida Analyst (ya extrae `presentacion_proposiciones`).

### P0.5 — System prompt: autorización explícita de textos legales

- **Qué:** Refuerzo en `FormatsAgent` / `TechnicalWriterAgent` (y reintento si P0.1 dispara).
- **Universal:** “Manifiestos bajo protesta, integridad, conflicto de interés son el propósito del producto; prohibido negarse.”
- **No sustituye** P0.1–P0.3 (el modelo puede ignorar el prompt).

---

## P1 — Fidelidad al modelo y presentación formal

### P1.1 — Priorizar `template_locked` / espejo RAG en anexos administrativos

- Si el PDF/DOCX del anexo está en fuentes → mirror + sustitución de variables (`{{rfc}}`, `{{representante}}`, `{{domicilio}}`, `{{fecha_documento}}`, `{{procedimiento}}`).
- Reducir `generate_controlled` LLM libre en anexos con plantilla en bases.

### P1.2 — Política de layout: firma al calce y rúbrica

- **Detección:** requisitos en compliance/bases (`rúbrica`, `margen derecho`, `firma`, `membretada`).
- **Materialización:** bloque estándar en `_save_docx` (representante, cargo, razón social, RFC, línea de firma).
- **Condicional:** solo si bases lo exigen (no en todos los DOCX del sistema).

### P1.3 — Léxico concursante en prompt + post-validación

- Alineado a regla de terminología del análisis externo, implementado como **política** y gate (P0.2), no como texto fijo UNAQ.

### P1.4 — APU estructurado (no “relleno simple”)

- **Contrato de salida:** tabla Materiales / MO / Indirectos / Utilidad / Subtotal / IVA / Total.
- **Cuadratura:** suma de renglones = total de `economic` / `session_line_items` (determinista).
- **Prohibido:** secciones tipo “Criterios de Evaluación Económica” en entregables del concursante.
- **Datos:** partidas y montos desde motor económico + HITL; LLM solo redacta narrativa si falta plantilla.

---

## P2 — Observabilidad, regresión y oro

### P2.1 — Script CI `forensic_contamination_scan.py`

- Formalizar escaneo (refusal, adjudicación, evaluador, fechas, cross-tender).
- Integrar en eval de sesión fixture o smoke post-generación.

### P2.2 — Fixtures “gold standard” anonimizados

- Usar estructura del análisis externo como **assertions** (presencia de bloques, no texto literal del comité).
- Caso regresión: Anexo X sin rechazo; Anexo IX con `en caso de resultar adjudicado`; APU en perspectiva concursante.

### P2.3 — Procedencia UI

- Badge por documento: `espejo_bases` | `llm_controlled` | `deterministic_economic`.
- El usuario ve qué revisar con más rigor en inspección visual.

---

## Reglas de sistema propuestas (mapeo a implementación)

| Regla externa | Implementación universal (no prompt solo) |
|---------------|----------------------------------------|
| Perspectiva concursante | P0.3 gate + P1.4 contrato APU |
| Fecha dinámica | P0.4 resolver + gate extemporaneidad |
| Terminología | P0.2 gate + whitelist condicional |
| Autorización legal | P0.5 prompt + P0.1 gate |
| APU con desglose | P1.4 + cuadratura económica |

---

## Criterios de aceptación (Definition of Done)

1. Ningún DOCX en `_compranet_validated` pasa con P0.1–P0.3 activos en modo `enforce`.
2. Fecha en cuerpo ≠ posterior a `presentacion_proposiciones` extraída del cronograma (salvo override usuario auditado).
3. Re-ejecución UNAQ (o fixture Oracle) baja contaminaciones a 0 en escaneo forense.
4. Mensaje UX no dice “Ir a Empresas” si el único hallazgo es semántico/plantilla (ya iniciado en `document_fill_ux_messages`).

---

## Orden de ejecución sugerido

```
P0.1 → P0.5 → P0.2 → P0.3 → P0.4 → P1.4 → P1.1 → P1.2 → P2.1 → P2.2
```

---

## Relación con otras agendas

- Complementa [`AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md`](AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md) (precios HITL no sustituye calidad jurídica).
- Los ítems de “estándar de oro” del chat son **referencia humana**, no plantillas pegadas en código.

---

## Pendiente explícito (no implementar sin priorización)

- Reescritura manual Anexo AE / Carta compromiso como oro (solo si se convierten en fixtures de regresión).
- Regeneración automática tras fallo P0 (reintento 1× con prompt reforzado + mirror forzado).
