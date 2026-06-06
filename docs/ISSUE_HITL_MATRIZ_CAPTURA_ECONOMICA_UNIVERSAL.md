# ISSUE — HITL económico universal: matriz orientadora, encabezados semánticos y cálculo al escribir

**Estado:** AGENDADO (post–Checkpoint 1 / E2E ISAPEG de tubo validado)  
**Prioridad:** P0 producto (propuesta económica correcta y UX percibida como inteligente)  
**Normativa:** [`ESTANDAR_ENTERPRISE_CANONICO_HITL.md`](ESTANDAR_ENTERPRISE_CANONICO_HITL.md)  
**Agenda relacionada:** [`AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md`](AGENDA_POST_CHECKPOINT1_HITL_ECONOMICO.md) (ítems A–D)

---

## Resumen

Cuando la convocante entrega Excel **sin fórmulas**, la app debe:

1. **Inferir** qué columnas son precio, cantidad, importe, ubicación, etc. (por texto de encabezado + estructura, no por nombre de archivo).
2. **Mostrar al usuario una matriz** (tabla) con filas y columnas extraídas del anexo, para captura masiva o pegado en chat.
3. **Persistir** valores con procedencia auditable y **escribir** el Excel + **calcular** importes/totales en nuestra capa (no depender de `SUM` del template).
4. Preguntar en lenguaje humano anclado a **archivo fuente + rol de columna + lista de filas**, sin jerga técnica.

**Caso de referencia (regresión, no hardcode):** ISAPEG — `Anexo III P1-2 ZB` con columna tipo “COSTO POR ELEMENTO I.V.A INCLUIDO” y filas de localidad. Debe funcionar igual en otra licitación con otros encabezados y otras dimensiones de fila (zona, horario, partida, material).

---

## Principios de universalidad (NO negociables)

| Regla | Significado |
|-------|-------------|
| **Sin nombres de archivo fijos** | No `if "ZB" in filename`. Detección por layout + semántica de encabezados + `document_role` persistido. |
| **Sin lista cerrada de licitaciones** | Misma lógica para limpieza, vigilancia, paneles solares, etc. |
| **Roles de columna, no textos literales** | Mapear encabezado → rol canónico (`unit_price_iva_included`, `quantity`, `location_label`, …), no comparar solo la cadena exacta del ISAPEG. |
| **Dimensión de fila inferida** | Localidad, zona, horario, concepto, material: se detecta por estructura (columna etiqueta + filas de datos), no por convención única. |
| **Un contrato de captura** | UI tabla, bloque masivo, CSV, pegado TSV en chat → mismo `InteractionBlock` / `concept_prices` con anclas `file + sheet + row + col`. |
| **Cascada HITL** | Usuario > documento normalizado > catálogo > inferencia; procedencia visible (`provenance_ui`). |
| **Cálculo determinista post-captura** | Importe y totales los calcula el backend al materializar; no asumir fórmulas en plantilla. |

---

## Problema actual (gap)

- Captura parcial por slots fijos (zona/horario P1-2) sin cubrir layouts “localidad × precio IVA incl.” en otro archivo del mismo expediente.
- `ExcelFillingService` inyecta precio unitario pero no siempre **importe** ni **total de hoja** si el formato no trae fórmulas.
- Chat a veces mezcla intake documental genérico antes que precios; copy “proyectar” confunde con contabilidad.
- Respuesta numérica rígida; falta matriz visible y pegado masivo en el mensaje.

---

## Comportamiento esperado (UX)

### 1. Mensaje del chatbot (plantilla semántica, no texto fijo)

> Para generar correctamente nuestra propuesta económica, necesito el **{rol_columna_legible}** solicitado en **{nombre_archivo_legible}**, para cada una de estas {dimension_fila_plural}:  
> {lista_filas_o_matriz}

### 2. Matriz en chat / panel

| {etiqueta_fila} | {encabezado_columna_1} | … |
|-----------------|------------------------|---|
| {fila_1} | *(vacío)* | |
| {fila_2} | | |

- Render en UI (`InteractionBlock` / componente tabla) **y** opción de copiar/pegar TSV.
- Export CSV → editar → import (reutilizar pipeline existente).

### 3. Tras captura

- Escribir celdas en el libro espejo.
- Calcular `importe = cantidad × precio` (si hay cantidad) y totales de hoja / propuesta desde `resumen_economico`.
- Quality gate sobre placeholders y coherencia numérica.

---

## Alcance técnico (implementación futura)

1. **Detector universal de columnas** en `tabular_line_item_extract` (o módulo hermano): normalización de encabezados, roles, IVA incluido vs excluido.
2. **Constructor de matriz de captura** → `InteractionBlock` con metadata `source_file`, `sheet`, `column_role`, `row_key`.
3. **Chatbot:** intro humana + payload de tabla; parser de pegado TSV/CSV en mensaje.
4. **Economic writer / excel fill:** post-proceso de importes y totales sin fórmulas del template.
5. **Prioridad de cola:** precios estructurados antes que intake tipo B genérico (ver Ítem C en agenda).
6. **Tests:** fixtures sintéticos con encabezados en español variantes; regresión anonimizada estilo ISAPEG ZB localidades.

---

## Fuera de alcance (este issue)

- Sustituir al contador / generar declaraciones fiscales SAT.
- Hardcodear ISAPEG, ZB, o “COSTO POR ELEMENTO I.V.A INCLUIDO” como única frase válida.
- Depender de que el Excel de la convocante traiga fórmulas.

---

## Criterios de aceptación

- [ ] Dado un Excel ingresado con encabezado semánticamente equivalente a precio con IVA, la app muestra matriz fila×columna **sin** configurar la licitación a mano.
- [ ] El usuario puede completar vía UI, CSV o pegado en chat; los tres convergen al mismo estado canónico.
- [ ] El archivo generado refleja precios e importes coherentes aunque la plantilla no tuviera fórmulas.
- [ ] `provenance_ui` indica archivo, hoja, fila y rol de columna por valor capturado.
- [ ] Regresión: layout tipo P1-2 ZA (zona/horario) **y** layout tipo localidades (ZB) pasan con la misma pipeline.

---

## Plan de ejecución

Tareas desglosadas (Fase 2 del plan maestro): [`PLAN_EJECUCION_ISSUES_AGENDADOS.md`](PLAN_EJECUCION_ISSUES_AGENDADOS.md) — IDs **D.1–D.23**.

---

## Trazabilidad

- 2026-05-27 — Usuario: matriz Ubicación × COSTO POR ELEMENTO IVA INCLUIDO; extracción como el asistente; pegado “voilà”.
- 2026-05-27 — Aclaración: formatos convocante sin fórmulas → cálculo propio al escribir.
- Relacionado: Ítem A (lenguaje natural en respuesta), Ítem B (corrección parcial post-entrega), Ítem C (cola/dedup).
