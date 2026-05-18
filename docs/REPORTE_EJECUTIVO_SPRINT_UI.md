# Reporte ejecutivo — Sprint UI (A2, A3, D1, B2)

**Fecha:** 2026-04-23  
**Alcance:** `frontend/src/components/PostClarificationPanel.jsx`, `EconomicValidationPanel.jsx`, `Dashboard.jsx`, `DeliveryPanel.jsx`

## Estado de tareas

| ID | Descripción | Estado |
|----|-------------|--------|
| **A2** | Acordeón `PostClarificationPanel`: cabecera `role="button"` + `aria-expanded` / `aria-controls`; `RefreshCw` en **`<button>` hermano** (no anidado). Resumen en cabecera. Cuerpo solo si `expanded`. | Implementado |
| **A3** | Acordeón `EconomicValidationPanel` + badge **“N bloqueantes”** en cabecera cerrada si `blocking_issues.length > 0`; refresh hermano. | Implementado |
| **D1** | `Dashboard`: estado `orchestrationExpanded`; **`useEffect` abre** al pasar `isAnalyzing` a `true`; **`useEffect` cierra** cuando `!isAnalyzing && hasDictamen`. Cabecera colapsable con chevron + resumen si cerrado. | Implementado |
| **B2** | `DeliveryPanel`: constantes `FALLBACK_*` + flags `*EsFallback` + componente `IndicativoEtiqueta` + pie de descargo convocatoria. | Implementado |

## Comprobaciones tipo `rg` (equivalente Cursor `grep`)

Entorno Windows sin `rg` en PATH: se usó búsqueda del workspace.

| # | Patrón | Resultado esperado | Resultado |
|---|--------|---------------------|-----------|
| 1 | `Generacción` en `frontend` | 0 coincidencias | 0 |
| 2 | `orchestrStrBodyId` (typo corregido) | 0 coincidencias | 0 |
| 3 | `FALLBACK_LUGAR_TEXTO` etc. en `DeliveryPanel.jsx` | Constantes y usos presentes | 7 líneas en archivo |
| 4 | `orchestrationExpanded` en `Dashboard.jsx` | Estado y efectos presentes | 6 coincidencias |

## Notas técnicas

- **A2/A3:** `defaultExpanded={false}`; teclado `Enter`/`Space` en cabecera acordeón.
- **D1:** Al cerrar tras análisis, el usuario puede volver a expandir manualmente; un nuevo análisis vuelve a abrir automáticamente.
- **B3 (descargo):** incluido como párrafo bajo tarjeta de modalidad (complemento a B2).

## Pendiente fuera de este sprint

- **A1** `SubmissionChecklistPanel` (acordeón hitos) — no incluido en la lista de 4 tareas de esta ejecución.
