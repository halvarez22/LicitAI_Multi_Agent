# Agenda post–Checkpoint 1 — HITL económico conversacional y corrección quirúrgica

**Estado:** EN IMPLEMENTACIÓN (2026-05-27) — código base C→D→A→B en backend; validar con E2E UI ISAPEG.  
**Registro:** 2026-05-27 (solicitud explícita del usuario en UI).  
**Normativa:** [`ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](ESTANDAR_ENTERPRISE_CANONICO_HITL.md) (cascada Usuario > documento > catálogo > inferencia; procedencia visible; revalidación tras cambio).

**Compromiso:** Los cuatro ítems se resolverán; no son opcionales ni “nice to have”.

---

## Ítem A — Captura de precios en chat con lenguaje natural (flexible)

### Problema

Hoy el flujo `economic_price` en chat tiende a exigir respuesta “cuadrada” (solo número). Usuarios reales responden de muchas formas: con símbolo de peso, comas, texto (“trece mil…”), frases largas, referencias (“igual que zona B”), pegado de tablas, etc. Eso contradice la promesa de producto: *el asistente entiende y guía en lenguaje humano*.

### Objetivo de producto

- **Entrada:** tolerante a formatos y paráfrasis en el canal principal (chat).
- **Salida canónica:** un valor numérico auditado por slot (zona, horario, material, etc.) con `provenance_ui` coherente.
- **Ambigüedad:** una pregunta corta de confirmación, no rechazo técnico.
- **Confirmación:** eco humano del dato interpretado antes de avanzar al siguiente slot.

### Alcance técnico (cuando se implemente)

1. Capa de **normalización conversacional** previa a persistencia (regex + reglas + LLM acotado solo para extracción, no para inventar precios).
2. Mantener **estricto** el guardado en `economic_user_inputs` / catálogo / `mass_save`.
3. No romper **Resolución por bloque** ni CSV masivo (pueden seguir estructurados).
4. Tests con batería de utterances reales (≥30 variantes por slot típico).
5. Relación con [`SUPER_ISSUE_CHAT_INTENCION_Y_UX_CONVERSACIONAL.md`](SUPER_ISSUE_CHAT_INTENCION_Y_UX_CONVERSACIONAL.md) — este ítem es el sub-hito económico dentro de esa visión.

### Criterio de aceptación

- El usuario puede escribir al menos: `35529`, `$35,529.00`, `35 mil 529`, `son 35529 pesos sin iva` y el sistema guarda el mismo valor canónico tras confirmación explícita o confianza alta.
- Si hay duda, pregunta una sola vez; no vuelca error técnico.

---

## Ítem B — Corrección post-entrega de precios vía chat + regeneración parcial de impactados

### Escenario (ejemplo de negocio)

Corrida **FINAL_OK**, documentos impresos, usuario armando sobres. Detecta que al chat pasó **$3,552.00** en lugar de **$35,529.00**. Debe poder corregir **sin repetir todo el pipeline** ni reimprimir cientos de páginas irrelevantes.

### Objetivo de producto

1. **Chat transaccional de corrección:** “Corrige el precio de Zona A lunes a domingo a 35,529” (o lenguaje natural equivalente al Ítem A).
2. **Grafo de impacto:** el sistema determina qué entregables dependen de ese slot (Excel espejo P1-2 ZA, totales, anexos derivados, filas de catálogo, etc.) usando trazabilidad ya persistida (`document_traceability`, `source_doc_id`, `materialization_route`, slots `price_struct_*`).
3. **Regeneración quirúrgica:** solo los archivos impactados; resto del expediente intacto.
4. **Oferta de descarga:** paquete o lista “solo archivos actualizados” + manifiesto delta (hashes nuevos vs anteriores).
5. **Revalidación:** quality gate y mini dictamen solo sobre el delta; no invalidar todo el expediente si el resto sigue válido.

### Principios (ENTERPRISE_CANONICO_HITL)

| Principio | Aplicación |
|-----------|------------|
| HITL transaccional | Corrección en chat/UI principal; override auditable (`source`, valor anterior, valor nuevo). |
| Cascada | Corrección usuario > recálculo determinista > writers afectados; no re-inferir LLM lo no tocado. |
| Procedencia visible | UI muestra “este cambio afecta N archivos” con badges y rutas. |
| Idempotencia | Reaplicar la misma corrección no duplica salidas. |

### Alcance técnico (cuando se implemente)

1. **Modelo de dependencia** precio → filas tabulares → plantillas Excel/DOCX (usar `structured_economic_price_mapper`, `session_line_items`, lineage en `attach_traceability`).
2. **Comando/intención** `CORREGIR_PRECIO` / `RECALCULAR_IMPACTADOS` en chatbot (alineado al SUPER ISSUE de intención).
3. **Servicio de patch documental:** re-ejecutar solo `economic_writer` (o sub-rutas mirror/fill) para IDs afectados; actualizar `MANIFIESTO_SHA256` / ZIP delta o carpeta `_compranet_validated` parcial.
4. **API/UI entrega:** endpoint “descargar solo actualizados” + diff de hashes.
5. **No** wipe completo de `/data/outputs/{session}` salvo que el usuario pida regeneración total explícita.

### Criterio de aceptación

- Tras corregir un precio, el usuario recibe en ≤1 min (objetivo) la lista de archivos recalculados y puede descargarlos sin volver a generar técnico/formatos no impactados.
- El manifiesto refleja solo los hashes cambiados.
- Auditoría conserva valor anterior y nuevo con timestamp y `session_id`.

---

## Ítem C — Clasificación documental, cola HITL y deduplicación (no contable / no repetir)

### Problema

1. Requisitos que en la vida real son **`presentar_fisico`** (p. ej. declaraciones fiscales ante SAT) entran al chat como `requiere_datos_licitante` con la plantilla genérica *“¿ya cuentas con ella o te ayudo a proyectarla?”* — confunde con sistema contable y con formatos generables.
2. **Compliance duplica** el mismo requisito (mismo concepto, distinto `field_target`: `compliance.formatos.40`, `.41`, `.42`), y el usuario debe responder **Sí** tres veces con texto casi idéntico.
3. La cola mezcla esos documentos **antes** de los `economic_price` (49 slots), frenando el E2E y la percepción de inteligencia.

### Objetivo de producto

| Tipo real | Dónde debe vivir | Copy al usuario |
|-----------|------------------|-----------------|
| Solo físico (SAT, INE, acta) | Checklist / mini dictamen | “Consíguelo para el sobre; no lo pedimos en chat.” |
| Formato/anexo generable | `generar` → formats | “Lo incluiremos en el expediente al generar.” |
| Datos/precios del licitante | Chat `economic_price` primero | Preguntas con zona, horario, procedencia |

### Alcance técnico (cuando se implemente)

1. Endurecer `enforce_deterministic_tipo_accion` para declaraciones fiscales / credenciales → `presentar_fisico` salvo plantilla oficial explícita en catálogo de sesión.
2. **Dedup** de `pending_questions` por huella semántica (`label` normalizado + categoría), no solo por `field_target`.
3. **Prioridad de cola:** `economic_price` y bloqueos económicos antes que intake tipo B genérico.
4. Sustituir copy *“proyectar”* por lenguaje de expediente (no contabilidad).
5. Tests: una sola pregunta por requisito fiscal duplicado en fixture ISAPEG.

### Criterio de aceptación

- El usuario no ve la misma declaración fiscal más de una vez en chat.
- Documentos solo físicos no aparecen en la cola conversacional.
- Tras análisis + compliance, el primer pendiente accionable para propuesta económica es un `economic_price` o un bloqueo económico claro.

---

## Ítem D — Captura semántica por encabezado de columna + dimensión fila (localidades) y cálculo determinista al escribir

**Issue formal (universalidad explícita):** [`ISSUE_HITL_MATRIZ_CAPTURA_ECONOMICA_UNIVERSAL.md`](ISSUE_HITL_MATRIZ_CAPTURA_ECONOMICA_UNIVERSAL.md)

### Contexto (ISAPEG y universal)

Muchos anexos de la convocante **no traen fórmulas** en Excel (p. ej. P1-2 ZA/ZB). No “no totaliza” por bug de SUM vacío: **nosotros debemos inferir** cantidad × precio unitario, subtotales por hoja/archivo y totales de propuesta al materializar.

Ejemplo de interacción esperada (ZB, columna detectada por texto de encabezado, sin hardcode de nombre de archivo):

> Para generar correctamente nuestra propuesta económica, necesito el **COSTO POR ELEMENTO I.V.A. INCLUIDO** solicitado en el archivo **33. Anexo III P1-2 ZB — Propuesta económica**, para cada una de estas localidades:  
> Acámbaro, Apaseo el Alto, … (lista extraída de filas del libro).

### Objetivo de producto

1. **Leer encabezados** de forma universal (`COSTO POR ELEMENTO`, con/sin IVA, PU, importe, etc.) → rol de columna (`unit_price_iva_included`, `unit_price_excl_iva`, `amount`).
2. **Leer dimensión de fila** (localidad, zona, horario, concepto) desde la estructura del libro, no desde nombres fijos de licitación.
3. **Preguntar en chat** (o bloque masivo) anclado a: **archivo fuente + etiqueta de columna + lista de filas**.
4. Al guardar, **escribir valor en celda** y **calcular importes/totales en nuestra capa** (no depender de fórmulas del template).
5. **Una pregunta por (archivo × columna de precio × dimensión)** cuando el layout lo exija; deduplicar filas repetidas.

### Relación con lo ya implementado

| Hoy | Gap vs visión |
|-----|----------------|
| 49 slots P1-2 por **zona + horario** (ZA–ZD) | Falta layout **ZB por localidad** y detección por **texto de encabezado** |
| `ExcelFillingService` inyecta precio | No calcula **importe** ni total de hoja si el formato no tiene fórmulas |
| Bloque masivo 49 filas | Debe generalizarse a **N filas × M archivos** con mismo contrato |

### Matriz orientadora en chat (extensión UX — solicitada 2026-05-27)

Además del texto narrativo, el chatbot debe **renderizar una tabla** extraída del anexo, para que el usuario vea exactamente qué llenar:

| Ubicación | COSTO POR ELEMENTO I.V.A INCLUIDO |
|-----------|-----------------------------------|
| ACAMBARO | *(vacío para captura)* |
| APASEO EL ALTO | |
| … | |

**Comportamiento esperado:**

1. **Extraer** encabezados de columna y etiquetas de fila del libro (sin hardcode de licitación).
2. **Mostrar** la matriz en el chat (HTML/Markdown tabla o componente UI reutilizando contrato `InteractionBlock`).
3. **Captura:** celda a celda en UI, pegado tipo CSV/TSV en el prompt (“ubicación + precio”), o exportar → editar → importar (mismo pipeline que Resolución por bloque).
4. Tras ingestión, **escribir** celdas en el Excel fuente y **calcular** importes/totales en nuestra capa.

Principio: *“Tan claro como si el asistente armara la tabla por ti; tú solo completas números y la app hace el resto.”*

### Criterio de aceptación

- Dado un Excel ingresado con encabezado “COSTO POR ELEMENTO I.V.A INCLUIDO” y ≥20 filas de localidad, el chat (o bloque) pide **un precio por fila** citando archivo y columna en lenguaje humano.
- El mismo flujo incluye una **matriz visible** con columnas = roles detectados y filas = localidades (o equivalente), no solo lista en prosa.
- El usuario puede completar la matriz en UI o pegar columnas alineadas; la app valida fila a fila y confirma.
- Tras captura, el archivo generado muestra **importes por fila** y **total de hoja** coherentes con los precios capturados (aunque la plantilla original no tuviera fórmulas).
- Sin hardcode de `Anexo III P1-2 ZB`; funciona en otra licitación con otra columna equivalente.

---

## Orden sugerido de implementación (después del E2E)

1. **Ítem C** (cola + clasificación + dedup) — desbloquea UX y evita repeticiones en todas las licitaciones.
2. **Ítem D** (encabezado semántico + localidades + cálculo al escribir) — núcleo de propuesta económica correcta en anexos sin fórmulas.
3. **Ítem A** — captura natural en chat (respuestas del usuario).
4. **Ítem B** — corrección post-entrega quirúrgica.

---

## Trazabilidad de la conversación

- Solicitud usuario: chat debe aceptar datos “como sea que los ingrese”; agenda explícita 2026-05-27.
- Solicitud usuario: corrección post-impresión con descarga solo de ajustados; agenda explícita 2026-05-27.
- Solicitud usuario: declaraciones fiscales en chat / “proyectar” / repeticiones; Ítem C agenda explícita 2026-05-27.
- Solicitud usuario: anexos sin fórmulas → inferir cálculos; captura por encabezado de columna + localidades por archivo (ej. ZB); Ítem D agenda explícita 2026-05-27.
- Solicitud usuario: chat debe mostrar **matriz Ubicación × columna de precio** extraída del anexo + captura/pega masiva; Ítem D extensión 2026-05-27.

---

## Plan de tareas ejecutable

Lista granular paso a paso: [`PLAN_EJECUCION_ISSUES_AGENDADOS.md`](PLAN_EJECUCION_ISSUES_AGENDADOS.md)

---

## Checklist de cierre (cuando se retome)

- [x] Ítem C implementado + tests dedup/clasificación + precios primero en cola
- [x] Ítem D implementado + tests encabezado semántico + localidades + totales calculados al escribir
- [x] Ítem A implementado + tests utterances + doc usuario
- [x] Ítem B implementado + tests impacto 1 precio → N archivos + descarga delta
- [ ] Playbook operativo en `DEPLOY_HARDENING_PLAYBOOK.md` (rollback de patch parcial)
- [ ] UI: mensaje claro “X archivos actualizados, Y sin cambios”
