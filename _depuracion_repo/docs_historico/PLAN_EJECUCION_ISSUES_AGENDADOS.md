# Plan de ejecución — Issues agendados (100% operación)

**Objetivo:** Agotar a cabalidad Ítems **C → D → A → B**, issue matriz universal, y enlaces mínimos al **SUPER ISSUE** de chat, sin perder universalidad (ENTERPRISE_CANONICO_HITL).

**Modo de trabajo:** pasos pequeños, cada uno con test + smoke en sesión real (ISAPEG primero, vigilancia/otra licitación después).

**E2E interno mock (2026-05-27):** `python backend/scripts/e2e_agenda_hitl_complete.py` → `overall_ok: true` (ver `backend/scratch/e2e_agenda_hitl_report.json`).

**Referencias normativas:**
- [`AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md`](AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md)
- [`ISSUE_HITL_MATRIZ_CAPTURA_ECONOMICA_UNIVERSAL.md`](ISSUE_HITL_MATRIZ_CAPTURA_ECONOMICA_UNIVERSAL.md)
- [`SUPER_ISSUE_CHAT_INTENCION_Y_UX_CONVERSACIONAL.md`](SUPER_ISSUE_CHAT_INTENCION_Y_UX_CONVERSACIONAL.md)
- [`ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](ESTANDAR_ENTERPRISE_CANONICO_HITL.md)

---

## Leyenda

| Símbolo | Significado |
|---------|-------------|
| `[ ]` | Pendiente |
| `[x]` | Hecho (marcar al cerrar) |
| **Gate** | No avanzar de fase sin cumplir el gate |
| **Smoke** | Prueba manual o script en sesión |

---

## Fase 0 — Baseline y trazabilidad (1–2 días)

| ID | Tarea | Entregable |
|----|-------|------------|
| 0.1 | [ ] Congelar baseline ISAPEG post–E2E: snapshot de `session_data`, hashes en `_compranet_validated`, lista de gaps conocidos (ZB, totales Excel, Word) | `backend/scratch/isapeg_baseline_*.json` o nota en scratch |
| 0.2 | [ ] Script/checklist de auditoría expediente (`audit_session_deliverables.py` + revisión humana Word/Excel) | Informe breve por sobre |
| 0.3 | [ ] Asegurar tests existentes en verde (`pytest` módulos economic, orchestrator, excel_fill, block_resolution) | CI local verde |
| 0.4 | [ ] Documentar contrato canónico de slot de precio (`price_struct_*`, `economic_user_inputs`, anclas fila/col) en comentario o doc interno breve | Sin ambigüedad para D y B |

**Gate 0:** Baseline + tests verdes + lista de gaps firmada.

---

## Fase 1 — Ítem C (cola, clasificación, dedup) — P0 UX

### 1.1 Clasificación `tipo_accion` (físico ≠ generable ≠ precio)

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| C.1 | [ ] Inventariar reglas actuales `enforce_deterministic_tipo_accion` y `document_deliverable_filter` | `compliance.py`, servicios de filtro |
| C.2 | [ ] Endurecer heurística: declaraciones SAT / credenciales / actas → `presentar_fisico` salvo plantilla explícita en catálogo de sesión | Misma capa + tests |
| C.3 | [ ] Separar en API/UI: checklist **solo físico** vs cola **generación/HITL** | `DeliveryPanel`, mini dictamen, rutas sesión |
| C.4 | [ ] Tests fixture: requisito fiscal duplicado en compliance → una sola entrada en checklist, cero en `pending_questions` | `backend/tests/` |

### 1.2 Dedup de `pending_questions`

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| C.5 | [ ] Definir huella semántica: `normalize_label` + categoría + tipo pregunta (no solo `field_target`) | `intake_planner.py`, `post_clarification/service.py` |
| C.6 | [ ] Implementar dedup al encolar y al rehidratar sesión | Orquestador / servicio de cola |
| C.7 | [ ] Test ISAPEG: máximo 1 pregunta por declaración fiscal repetida (`.40`, `.41`, `.42`) | Fixture anonimizado |
| C.8 | [ ] Script de saneamiento opcional para sesiones en vuelo con cola sucia | `scripts/` |

### 1.3 Prioridad de cola (precios primero)

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| C.9 | [ ] Ordenar cola: `economic_price` / bloqueos económicos → intake tipo B genérico → resto | Orquestador, chatbot |
| C.10 | [ ] Bloquear intake “¿proyectar declaración?” para ítems `presentar_fisico` | `intake_planner.py`, plantillas copy |
| C.11 | [ ] Sustituir copy “proyectar” por lenguaje de expediente (no contabilidad) | Centralizar strings UX |
| C.12 | [ ] Smoke ISAPEG: tras compliance, primer pendiente = precio o bloque económico | UI + logs |

### 1.4 Copy y mini dictamen alineados

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| C.13 | [ ] Mini dictamen / delivery view: badge “Presentar físicamente” coherente con chat | `mini_dictamen_anexos_service.py`, frontend |
| C.14 | [ ] Mensajes de error UX centralizados (`error_type` estable) para cola vacía vs económico pendiente | Estándar HITL |

**Gate 1 (Ítem C):**
- [ ] Criterios de aceptación agenda Ítem C (3 bullets) cumplidos
- [ ] `pytest` nuevos en verde
- [ ] Smoke ISAPEG: cola sin triplicar fiscal ni “proyectar” SAT

---

## Fase 2 — Ítem D + Issue matriz universal — P0 exactitud económica

### 2.1 Detector universal de columnas y filas

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| D.1 | [ ] Catálogo de roles de columna canónicos (`unit_price_iva_included`, `quantity`, `amount`, `location_label`, …) | Nuevo módulo o extensión `tabular_line_item_extract.py` |
| D.2 | [ ] Normalización de encabezados (acentos, puntos, IVA incl/excl, sinónimos ES) | Función pura + tabla de sinónimos configurable, no por licitación |
| D.3 | [ ] Inferir dimensión de fila (localidad, zona, horario, concepto) por estructura de hoja | Mismo módulo |
| D.4 | [ ] Persistir layout detectado en sesión (`document_role`, `capture_matrix_meta`) | `session_data` / catálogo plantilla |
| D.5 | [ ] Tests sintéticos: ≥5 variantes de encabezado → mismo rol | `test_tabular_*` nuevo |

### 2.2 Constructor de matriz de captura (`InteractionBlock`)

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| D.6 | [ ] Contrato JSON matriz: `source_file`, `sheet`, `column_role`, `rows[]`, `columns[]` | Alineado a `interaction_block_mass_save.py` |
| D.7 | [ ] Generar bloques N filas × M archivos (no solo 49 slots ZA–ZD) | `structured_economic_price_mapper.py` refactor |
| D.8 | [ ] Una pregunta/bloque por (archivo × columna precio × dimensión); dedup filas repetidas | Planner económico |
| D.9 | [ ] Plantilla mensaje chat semántica (`{rol_columna}`, `{archivo}`, `{dimension_fila}`) | `chatbot_rag.py` o servicio dedicado |
| D.10 | [ ] Frontend: tabla reutilizando `BlockResolutionPanel` para matriz genérica | `frontend/src/components/` |

### 2.3 Ingesta masiva (UI, CSV, TSV en chat)

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| D.11 | [ ] Parser pegado TSV/CSV en mensaje de chat → mismo estado que mass_save | `interaction_block_csv_io.py`, chatbot |
| D.12 | [ ] Validación fila a fila + confirmación resumen (“capturaste 23 de 23”) | HITL |
| D.13 | [ ] `provenance_ui` por celda: archivo, hoja, fila, col, rol | API sesión + frontend badges |
| D.14 | [ ] Tests: UI path, CSV path, TSV path → mismo canónico | 3 tests mínimo |

### 2.4 Escritura Excel + cálculo determinista

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| D.15 | [ ] `ExcelFillingService`: escribir precio + **calcular importe** (cantidad × PU si aplica) | `excel_filling_service.py` |
| D.16 | [ ] Totales de hoja / subtotales sin depender de fórmulas del template | `economic_writer.py` |
| D.17 | [ ] Alinear totales con `resumen_economico` / propuesta agregada | `economic_refresher.py`, agente económico |
| D.18 | [ ] Quality gate: placeholders, ceros sospechosos, incoherencia fila vs total | `document_fill_quality_gate.py` |
| D.19 | [ ] Regresión layout ZA (zona/horario) **sin romper** | Tests existentes + 1 nuevo |
| D.20 | [ ] Regresión layout localidades (estilo ZB, fixture sintético o anonimizado) | Nuevo fixture |
| D.21 | [ ] Smoke ISAPEG: ZB (o equivalente) generado en sobre económico con importes coherentes | Manual + script coverage |

### 2.5 Cobertura de entregables económicos

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| D.22 | [ ] `delivery_coverage_report` / mini dictamen: anexos económicos esperados vs generados | Servicios delivery |
| D.23 | [ ] Alertar anexo faltante (ej. solo ZA/ZC/ZD sin ZB) antes de `FINAL_OK` | Orquestador o gate |

**Gate 2 (Ítem D):**
- [ ] Criterios de aceptación issue matriz (5 checkboxes) cumplidos
- [ ] Sin `if "ZB" in filename` en código nuevo (revisión grep)
- [ ] Smoke ISAPEG: Excel espejo con importes y totales; ZB presente si aplica en catálogo

---

## Fase 3 — Ítem A (lenguaje natural en chat para precios)

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| A.1 | [ ] Servicio `conversational_price_normalizer`: regex + reglas MXN | Nuevo `backend/app/services/` |
| A.2 | [ ] LLM acotado solo extracción numérica (temperature 0, sin inventar) | Opcional detrás de flag |
| A.3 | [ ] Integrar en flujo `economic_price` antes de persistir | `chatbot_rag.py`, orquestador |
| A.4 | [ ] Confirmación humana si confianza < umbral; una sola repregunta | HITL |
| A.5 | [ ] Eco: “Interpreté $35,529.00 para Zona A L-D; ¿correcto?” | Copy |
| A.6 | [ ] Batería ≥30 utterances por slot en tests | `test_*_behavior.py` |
| A.7 | [ ] No romper bloque masivo ni CSV (entrada estructurada bypass normalizer) | Tests regresión |
| A.8 | [ ] Soporte referencias (“igual que zona B”) vía lookup canónico | Sesión + mapper |
| A.9 | [ ] Smoke: frases largas ya no desvían a RAG genérico cuando hay `pending_questions` económico | Enlace SUPER ISSUE S.3 |

**Gate 3 (Ítem A):** Criterios agenda Ítem A + utterances en CI.

---

## Fase 4 — Ítem B (corrección post-entrega quirúrgica)

### 4.1 Modelo de dependencias

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| B.1 | [ ] Grafo precio → `session_line_items` → plantilla → archivo salida | `document_traceability.py`, mapper |
| B.2 | [ ] API interna: `resolve_impacted_deliverables(session_id, slot_key)` | Nuevo servicio |
| B.3 | [ ] Tests: 1 precio cambiado → N archivos esperados (N≥1) | Unit |

### 4.2 Intención y HITL de corrección

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| B.4 | [ ] Intención `CORREGIR_PRECIO` / `RECALCULAR_IMPACTADOS` en capa intención | `chatbot_rag.py` + SUPER ISSUE |
| B.5 | [ ] Persistir override auditable (`valor_anterior`, `valor_nuevo`, `source`, timestamp) | `session_data` / tabla audit |
| B.6 | [ ] UI: “Este cambio afecta N archivos” + lista | Frontend entrega |

### 4.3 Patch documental y entrega delta

| ID | Tarea | Módulos / archivos |
|----|-------|-------------------|
| B.7 | [ ] Servicio `document_patch_service`: re-ejecutar solo rutas `economic_writer` impactadas | Nuevo servicio |
| B.8 | [ ] Actualizar `_compranet_validated` parcial + `MANIFIESTO_SHA256` delta | `packager.py` |
| B.9 | [ ] Endpoint descarga “solo actualizados” + diff hashes | `routes/downloads.py` |
| B.10 | [ ] Idempotencia: misma corrección dos veces = mismo resultado | Test |
| B.11 | [ ] Quality gate + mini dictamen solo sobre delta | Gates existentes |
| B.12 | [ ] Objetivo latencia ≤1 min en smoke | Medición |
| B.13 | [ ] Playbook rollback patch parcial en `DEPLOY_HARDENING_PLAYBOOK.md` | Docs ops |

**Gate 4 (Ítem B):** Criterios agenda Ítem B + smoke corrección 3552→35529.

---

## Fase 5 — SUPER ISSUE (mínimo viable enlazado a A–D)

Ejecutar **en paralelo ligero** desde Fase 1; cerrar del todo al final.

| ID | Tarea | Relación |
|----|-------|----------|
| S.1 | [x] Enum intención: `COTIZAR`, `GENERAR_EXPEDIENTE`, `RESPONDER_PENDIENTE`, `PREGUNTAR_BASES`, `VER_ESTADO`, `AYUDA` | P0 SUPER ISSUE |
| S.2 | [x] `generar` solo → desambiguación 1 pregunta (no META forense) | chatbot |
| S.3 | [x] Prohibir volcado compliance/gates/`stop_reason` crudo en chat usuario | `_format_response` + sanitize |
| S.4 | [x] Mapa `stop_reason` → español + un CTA | `chat_gate5_formatter.py` |
| S.5 | [x] Con `pending_questions` económico activo: bloqueo RAG salvo bases | FASE 3B chatbot |
| S.6 | [x] Batería 295 utterances + CI Gate 5 | Tests smoke pytest |
| S.7 | [x] Keys React únicas `DocumentCandidatePanel` | `stableReactKey.js` |

**Gate 5:** Implementado en código (2026-06-02); validar utterances de cierre en UI licitación nueva.

---

## Fase 6 — Cierre operativo 100% (transversal)

| ID | Tarea | Notas |
|----|-------|-------|
| X.1 | [ ] E2E ISAPEG completo sin mocks tras C+D+A+B | Reset script + UI |
| X.2 | [ ] E2E segunda licitación (vigilancia o fixture) para validar universalidad | No solo ISAPEG |
| X.3 | [ ] Oracle PKG01 / export packager coherente post-patch | CI |
| X.4 | [ ] Calidad DOCX transversal (domicilio pipes, doble ATENTAMENTE) — backlog explícito si fuera de agenda | P2 contenido |
| X.5 | [ ] Actualizar checklist en `AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md` (marcar ítems) | Docs |
| X.6 | [ ] Demo script 15 min para stakeholder (captura matriz → generar → corregir → delta ZIP) | Producto |

**Gate final:** Usuario licitante sin manual completa ciclo captura → `FINAL_OK` → corrige un precio → descarga solo cambiados.

---

## Orden de ejecución recomendado (sprints)

| Sprint | Fases | Objetivo visible |
|--------|-------|------------------|
| **S0** | 0 | Baseline y confianza en tests |
| **S1** | 1 (C) | Cola limpia, precios primero, sin “proyectar” SAT |
| **S2** | 2.1–2.2 (D) | Matriz y detección universal |
| **S3** | 2.3–2.4 (D) | Pegado + Excel con cálculos |
| **S4** | 2.5 + 3 (D gate + A) | Cobertura anexos + chat flexible |
| **S5** | 4 (B) | Corrección quirúrgica post-entrega |
| **S6** | 5 + 6 (S + cierre) | Chat de mercado + E2E universal |

---

## Métricas de progreso (opcional)

| Métrica | Meta |
|---------|------|
| % tareas marcadas `[x]` en este doc | 100% |
| Preguntas duplicadas en cola ISAPEG | 0 |
| Anexos económicos en coverage vs catálogo | 100% |
| Utterances precio normalizadas OK | ≥95% en batería |
| Tiempo patch 1 precio → ZIP delta | ≤60 s |

---

## Control de cambios

| Fecha | Nota |
|-------|------|
| 2026-05-27 | Plan inicial generado; orden C → D → A → B + SUPER ISSUE mínimo |
