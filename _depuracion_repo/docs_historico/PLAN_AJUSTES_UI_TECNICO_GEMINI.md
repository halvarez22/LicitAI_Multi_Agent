# Plan técnico de ajustes UI — contraste / revisión (Gemini u otro revisor)

**Objetivo del documento:** especificación implementable y verificable para alinear UX (acordeones, copys, layout) sin ambigüedad.  
**Alcance:** `frontend/` (principalmente `App.jsx` y componentes citados). **Sin cambios de contrato API** salvo donde se indique explícitamente.  
**Documento hermano (backlog resumido):** `docs/AGENDA_AJUSTES_UI.md`  
**Versión del plan:** 1.2 · 2026-04-23 (A1 acordeón hitos aplicado; kill-switch ValidationPolicyAdmin)

### 0.1 Validación cruzada (resumen)

Revisión independiente del código confirmó el plan como **sustancialmente correcto**. Correcciones incorporadas en v1.1:

- Rango de líneas del `<aside>` izquierdo: **L1489–1756** (`App.jsx`), no ~1505.
- **Dos `maxHeight` independientes:** lista de fuentes `38vh` en `App.jsx`; lista de hitos `280px` en `SubmissionChecklistPanel.jsx`. Fase **A1** solo altera el segundo.
- **`PostClarificationPanel`** debe conservar el prop **`sources`** (además de `sessionId`, `syncKey`, `onAskAboutActa`) en cualquier refactor.
- **B1** aplicado en código: typo `Generacción` → `Generación` en `DeliveryPanel.jsx` L173.
- Pendiente documentar en plan: **`AnalysisResults`** siempre montado cuando `!showGoNoGoPanel` (Fase C debe explicitar destino si se vacía la columna izquierda).
- **B2:** implementar **`FALLBACK_*` como constantes** en `DeliveryPanel.jsx` antes de heurística de etiquetado (evita comparación frágil por string suelto).

---

## 1. Arquitectura actual (baseline)

### 1.1 Layout de tres columnas (`App.jsx`)

| Columna | Ancho | Rol |
|---------|--------|-----|
| `<aside>` izquierdo | `leftWidth` px (resizable) | Fuentes + paneles auxiliares + acciones análisis/generación + `GoNoGoPanel` / `AnalysisResults` |
| `<section>` centro | `flex: 1` | `Dashboard` + `DeliveryPanel` |
| `<aside>` derecho | `rightWidth` px | Chat “Asistente del pliego”, `BlockResolutionPanel`, validaciones UI |

**Montaje exacto en columna izquierda (`App.jsx`, orden vertical, L1489–1756):**

1. Encabezado “FUENTES DE VERDAD” + `input[type=file]` oculto + botón subida.
2. Contenedor lista `sources` (**`maxHeight: 38vh`** en `App.jsx`, scroll interno; **independiente** del `maxHeight` de hitos).
3. `<SubmissionChecklistPanel sessionId syncKey onAskAboutHito />`
4. `<PostClarificationPanel sessionId sources syncKey onAskAboutActa />` — **`sources` obligatorio** (PDFs de sesión para selector de acta).
5. `<EconomicValidationPanel sessionId syncKey onAskAboutValidation />`
6. `<ValidationPolicyAdmin sessionId />`
7. Botones `ACTUALIZAR ANÁLISIS` / `GENERAR PROPUESTA` + textos auxiliares.
8. Bloque condicional: `showGoNoGoPanel && goNoGoResult` → `GoNoGoPanel`; si no → `AnalysisResults`.

**Fuente de datos:** `auditResults` (dictamen procesado), `generationResults`, `goNoGoResult`, `sources`, `sessionId`, `selectedCompanyId`.

### 1.2 Telemetría “Orquestación de Agentes”

- **Componente:** `frontend/src/components/Dashboard.jsx`.
- **Entrada clave:** `auditResults.pipelineTelemetry` (estructura con `stagesCompleted`, `orchestratorStatus`, `pausedStage`, `stopReason`, flag `_inferred`).
- **Fallback:** `synthesizePipelineTelemetryFromDictamen` en `frontend/src/utils/auditSummary.js` (inyectado en `App.jsx` al hidratar dictamen).
- **Título UI literal:** “Orquestación de Agentes” (aprox. L267 en `Dashboard.jsx`).

### 1.3 Logística

- **Componente:** `frontend/src/components/DeliveryPanel.jsx`.
- Listado de salidas: `GET /downloads/list?session_id=…` → estado local `structure`.
- ZIP: `GET /downloads/zip?session_id=…`.
- Modalidad: `results?.delivery?.data` (`tipo`, `portal_*`, `direccion_fisica`, `horario`, `fecha_limite`); fallbacks hardcodeados en JSX (L244–257 aprox.).

---

## 2. Alcance funcional por ítem

### Fase A — Acordeones (componentes aislados)

| ID | Componente | Archivo | Comportamiento objetivo |
|----|------------|---------|-------------------------|
| A1 | Hitos | `SubmissionChecklistPanel.jsx` | Estado `expanded` (default `false`). Cabecera `<button type="button" aria-expanded>` o `role="button"` + teclado. Chevron. Cuerpo: lista actual; **eliminar o condicionar** `maxHeight: 280px` cuando `expanded === true` (o aumentar sustancialmente) para evitar sensación “recortada”. |
| A2 | Actas | `PostClarificationPanel.jsx` | Mismo patrón. Cabecera cerrada: resumen si `ctx` existe (estado, confianza, “borrador listo”). Abierto: flujo actual (`tipoJunta`, `processActa`, etc.). |
| A3 | Validaciones económicas | `EconomicValidationPanel.jsx` | Mismo patrón. Cabecera cerrada: string derivado de `validation.validations` (conteos OK/WARN/BLOCKING) o mensaje “Sin datos”. Si `blocking_issues.length > 0`, badge visible en cabecera cerrada. `RefreshCw` accesible (cabecera o barra superior del acordeón). |

**Contratos de props:** no romper `sessionId`, `syncKey`, callbacks `onAskAbout*`.

**Accesibilidad mínima:** `aria-expanded`, foco visible, `aria-controls` + `id` en panel colapsable.

### Fase B — Copys y riesgo legal percibido (`DeliveryPanel.jsx`)

| ID | Cambio | Detalle técnico |
|----|--------|-----------------|
| B1 | Typo | Cadena “Generacción” → “Generación” (`DeliveryPanel.jsx` L173). **Estado: aplicado en repo (v1.1).** |
| B2 | Placeholders | Cuando `deliveryData.tipo` es falsy → sigue “Detectando modalidad…”. Para `horario` / `direccion_fisica` / `fecha_limite`: si el valor mostrado es el **fallback literal del código** (`'09:00 - 15:00'`, `'Ver Guía PDF'`, `'Consultar bases'`), prefijar con etiqueta UI tipo “(indicativo — confirmar en bases)” **o** separar visualmente bloque “Datos inferidos” vs “Valores por defecto”. |
| B3 | Opcional | Pie de tarjeta modalidad: texto fijo de descargo (“No sustituye convocatoria oficial”). |

**Backend:** no obligatorio en Fase B. **Obligatorio en implementación B2:** definir constantes exportadas o de módulo, p. ej. `FALLBACK_HORARIO_ENTREGA`, `FALLBACK_LUGAR_TEXTO`, `FALLBACK_LIMITE_TEXTO`, y usar **referencia idéntica** en JSX y en la lógica “¿es placeholder?” (validación externa: evitar comparar literales duplicados frágiles).

### Fase C — Re-layout columna izquierda + navegación tipo “Opción A”

**Decisión de producto (pendiente de aprobación en implementación):**

- **C.1** Columna izquierda **mínima:** solo bloque fuentes + semáforo. **Nota validada:** hoy `AnalysisResults` ocupa el mismo slot que `GoNoGoPanel` cuando `showGoNoGoPanel === false`; no está “debajo” condicionalmente de otra cosa. Si la columna queda solo fuentes+semáforo, **hay que decidir destino explícito** de `AnalysisResults` (p. ej. debajo de `Dashboard`, pestaña “Resumen”, o drawer) para no perder el resumen de agentes / métricas que hoy muestra ese componente.
- **C.2** Reubicar: `SubmissionChecklistPanel`, `PostClarificationPanel`, `EconomicValidationPanel`, `ValidationPolicyAdmin` tras cabecera de sesión.

**Variantes de UI (documentadas en conversación):**

- **A1 “cinturón”:** pestañas bajo header global; al cambiar pestaña, se renderiza un **panel horizontal** debajo del tab bar **sin** sustituir todo el `<section>` del dictamen (dictamen sigue visible debajo del cinturón o el cinturón solo ocupa franja superior del centro).
- **A2 “módulos”:** las pestañas reemplazan el contenido principal del centro (dictamen oculto hasta volver a “Expediente” o vista principal).

**Estado global sugerido en `App.jsx`:**

```text
sessionToolsTab: 'expediente' | 'calendario' | 'post_junta' | 'economico' | 'avanzado'
```

- `expediente`: por defecto; alinea con fuentes ya en izquierda o vista vacía en cinturón.
- `avanzado`: monta `ValidationPolicyAdmin` (posible `lazy` + boundary error).

**Riesgo:** `onAskAboutHito` / `onAskAboutActa` / `onAskAboutValidation` hoy hacen `setChatInput(...)`. Debe **seguir** existiendo un mecanismo equivalente (mismo setter o callback elevado).

### Fase D — `Dashboard` / orquestación

| ID | Cambio | Detalle |
|----|--------|---------|
| D1 | Colapsar bloque “Orquestación de Agentes” | Estado local en `Dashboard.jsx` o prop `defaultOrchestrationCollapsed` desde `App`. Por defecto `true` tras primer dictamen cargado; `false` mientras `isAnalyzing === true` (usuario ve progreso). |
| D2 | Alternativa | Mover telemetría a drawer secundario (más trabajo: nuevo contenedor + trigger). |

**No eliminar** lógica `agentStates` / `useMemo`: solo envoltura UI.

---

## 3. Orden de implementación recomendado

1. ~~**B1** (typo)~~ **Hecho** (2026-04-23).
2. ~~**Kill-switch** `ValidationPolicyAdmin`~~ **Hecho** (2026-04-23) — `VITE_SHOW_VALIDATION_POLICY !== 'false'` en `App.jsx`.
3. ~~**A1**~~ **Hecho** (2026-04-23) — `SubmissionChecklistPanel` convertido a acordeón con `aria-expanded`, chevron, resumen vencidos en cabecera, `maxHeight` subido a 420 px.
4. **A2 → A3:** mismos patrón acordeón; A2 conserva prop `sources`.
5. **B2 / B3:** dependen de copy aprobado legal/comercial.
6. **D1:** acotado a `Dashboard.jsx`.
7. **C1 + C2:** mayor refactor de `App.jsx`; requiere decisión cinturón vs módulos.

---

## 4. Criterios de aceptación (verificables)

### Acordeón (A1–A3)

- [ ] Con teclado: foco en cabecera; `Enter`/`Space` alterna expand (si se usa `<div role="button" tabIndex={0}>`).
- [ ] Lector de pantalla: `aria-expanded` coherente con visibilidad del cuerpo.
- [ ] Al cambiar `syncKey` / `sessionId`, el panel **no** pierde estado expandido de forma accidental **o** se documenta que debe resetearse (decisión explícita).
- [ ] Hitos: con `expanded === true`, al menos **N** hitos visibles sin sensación de “corte” injustificado (definir N mínimo en viewport 1366×768).

### Delivery (B)

- [x] No existe la subcadena `Generacción` en `frontend/` (B1 aplicado); CI puede usar `rg Generacción frontend` → sin coincidencias.
- [ ] Placeholders marcados visualmente o con prefijo; usuario no puede confundir horario default con horario oficial sin leer la aclaración.

### Layout (C)

- [ ] Con `sessionToolsTab = calendario`, `SubmissionChecklistPanel` sigue recibiendo `sessionId` y `syncKey` idénticos al comportamiento previo (mismas llamadas `GET/POST` submission-checklist).
- [ ] `ValidationPolicyAdmin` solo visible en tab `avanzado` **o** detrás de flag `VITE_SHOW_VALIDATION_POLICY` si se introduce kill-switch.

### Dashboard (D)

- [ ] Con análisis completado y `isAnalyzing === false`, bloque orquestación colapsado por defecto (si se adopta D1).
- [ ] Con `isAnalyzing === true`, usuario ve estados IN_PROGRESS sin clic extra.

---

## 5. Pruebas automatizadas / regresión

| Área | Sugerencia |
|------|------------|
| Acordeones | Si no hay Jest en frontend, añadir smoke mínimo o checklist QA manual documentado. |
| `DeliveryPanel` | Buscar en CI `grep -R Generacción` en `frontend/` → exit code 1. |
| API | Sin cambios esperados en Fase A/B/D. Fase C no debe alterar URLs de `SubmissionChecklistPanel` (`/sessions/:id/submission-checklist`). |

---

## 6. Riesgos y dependencias

| Riesgo | Mitigación |
|--------|------------|
| `GoNoGoPanel` hoy sustituye `AnalysisResults` en el mismo slot | Si C1 deja solo “semáforo” en izquierda, definir dónde vive `AnalysisResults` (centro bajo dictamen, modal, o tab). |
| Duplicación de “semáforo” si se mueve Go/No-Go | Una sola fuente de verdad `goNoGoResult` en estado `App`. |
| `leftWidth` pequeño | `GoNoGoPanel` responsive; probar `leftWidth` mínimo actual del resizer. |
| i18n futuro | Textos nuevos en constantes o objeto de strings para extracción posterior. |

---

## 7. Archivos tocados (matriz)

| Archivo | Fases |
|---------|-------|
| `frontend/src/components/SubmissionChecklistPanel.jsx` | A1 |
| `frontend/src/components/PostClarificationPanel.jsx` | A2 |
| `frontend/src/components/EconomicValidationPanel.jsx` | A3 |
| `frontend/src/components/DeliveryPanel.jsx` | B1–B3 |
| `frontend/src/components/Dashboard.jsx` | D1 |
| `frontend/src/App.jsx` | C1–C2, posible D1 prop, cableado tabs |
| `docs/AGENDA_AJUSTES_UI.md` | Mantener sincronizado al cerrar tareas |

---

## 8. Preguntas abiertas → resoluciones (validación externa)

| # | Pregunta | Resolución recomendada |
|---|----------|-------------------------|
| 1 | A1 vs A2 | **A1 (cinturón)** por defecto: mantiene dictamen visible; menos refactor y menos riesgo de “perder” compliance. |
| 2 | `AnalysisResults` | **Permanecer en columna izquierda en la transición** (junto a acordeones colapsados) salvo que se implemente destino explícito en centro; evita duplicar tarjetas con `Dashboard` sin diseño previo. |
| 3 | Kill-switch `ValidationPolicyAdmin` | **Sí** — p. ej. `import.meta.env.VITE_SHOW_VALIDATION_POLICY !== 'false'` o flag explícito `true` solo en dev; una rama en `App.jsx`, bajo riesgo. |
| 4 | Tests | **Checklist QA manual** mínimo por fase + **`grep` / `rg` en CI** para `Generacción`; **RTL/Playwright no bloqueante** hasta que exista harness estable en frontend. |

---

## 9. Changelog

| Versión | Fecha | Cambios |
|---------|--------|---------|
| 1.0 | 2026-04-23 | Plan inicial |
| 1.1 | 2026-04-23 | Validación cruzada; líneas L1489–1756; dos `maxHeight`; prop `sources`; B1 en código; resoluciones §8; B2 constantes obligatorias; nota `AnalysisResults` |
| 1.2 | 2026-04-23 | A1 aplicado (`SubmissionChecklistPanel` acordeón); kill-switch `VITE_SHOW_VALIDATION_POLICY` en `App.jsx` |

---

*Fin del plan técnico v1.1*
