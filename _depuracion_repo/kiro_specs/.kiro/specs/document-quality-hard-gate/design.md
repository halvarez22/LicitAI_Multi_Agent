# Diseño: Hard Gate de calidad en generación documental

## Punto de control

El gate vive en capa de escritores (`technical_writer`, `formats`) porque es el último punto antes de materializar documentos.

## Métricas usadas

- `total_items`: universo de candidatos del sobre/área.
- `generar_count`: cantidad de ítems con `tipo_accion=generar`.
- `unknown_ratio`: `unknown_count / total_items`.
- `evidence_match_ratio`: proporción con `evidence_match=True`.

## Política

- Configuración en `settings.py`:
  - `DOCUMENT_QUALITY_HARD_GATE_ENABLED`
  - `DOCUMENT_QUALITY_GATE_MIN_ITEMS`
  - `DOCUMENT_QUALITY_GATE_MAX_UNKNOWN_RATIO`
  - `DOCUMENT_QUALITY_GATE_MIN_EVIDENCE_MATCH_RATIO`

## Comportamiento de bloqueo

- Retorno `AgentStatus.WAITING_FOR_DATA`.
- Mensaje orientado a reclasificación/fortalecimiento de evidencia.
- `data.document_quality_gate` incluye `reason` + `metrics`.
- Persiste una `pending_question` con `type=document_quality_gate_blocking`.
