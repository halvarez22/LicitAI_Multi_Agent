# Instrucciones sprint UI (referencia + estado)

Documento de referencia del flujo **A2 → A3 → D1 → B2** según revisión externa.

**Implementación aplicada en repo:** ver **`docs/REPORTE_EJECUTIVO_SPRINT_UI.md`** (tabla de estado y comprobaciones).

Orden acordado:

1. **A2** — `PostClarificationPanel.jsx`: acordeón; no anidar `<button>` en cabecera; `sources` obligatorio.
2. **A3** — `EconomicValidationPanel.jsx`: acordeón + badge bloqueantes en cabecera cerrada.
3. **D1** — `Dashboard.jsx`: colapsar orquestación; `useEffect` expande si `isAnalyzing === true`.
4. **B2** — `DeliveryPanel.jsx`: `FALLBACK_*` + etiqueta indicativa.

**A1** (Hitos / `SubmissionChecklistPanel`) queda pendiente en agenda global.
