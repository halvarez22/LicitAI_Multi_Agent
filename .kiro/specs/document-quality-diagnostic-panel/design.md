# Diseño: DocumentQualityDiagnosticPanel

## Fuente de datos

Prioridad de extracción:
1) `orchestrator.agent_decision.waiting_hints`
2) `orchestrator.orchestrator_decision.waiting_hints`
3) fallback escaneando `orchestrator.data.*.data.document_quality_gate`

## UI

- Nuevo componente `DocumentQualityDiagnosticPanel.jsx`.
- Entrada:
  - `snapshot`: `{ reason, metrics }`
  - `blocked`: boolean
  - `onRevalidate`: callback
  - `busy`: boolean
- Render:
  - estado textual + badge
  - métricas clave (`unknown_ratio`, `evidence_match_ratio`, `generar_count`, `total_items`)
  - thresholds cuando estén presentes
  - recomendación contextual por `reason`

## Integración

- Nuevo tab en `App.jsx`: `calidad_docs`.
- Estado local: `documentQualityGateSnapshot`.
- Reset en rutas `success`/`error`.
