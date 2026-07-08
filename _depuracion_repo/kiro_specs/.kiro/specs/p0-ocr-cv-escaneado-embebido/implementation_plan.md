# Plan de Implementación — P0 OCR CV Escaneado Embebido

## Fase 1 — Detección y ruteo OCR
1. [ ] Implementar detector de PDF con texto insuficiente (heurística por chars/página).
2. [ ] Si texto insuficiente, activar OCR visual por página como fallback.
3. [ ] Registrar `text_source` por documento: `native|ocr_visual|mixed`.

## Fase 2 — Calidad OCR y persistencia
4. [ ] Calcular score básico de calidad por página/documento.
5. [ ] Persistir texto OCR y metadatos de calidad en sesión/documento.
6. [ ] Enlazar salida OCR a indexación vectorial y extractores técnicos.

## Fase 3 — Integración con pipeline técnico
7. [ ] Priorizar texto OCR en extracción cuando supere umbral mínimo de calidad.
8. [ ] Añadir alertas deterministas cuando OCR sea insuficiente (mensaje accionable al usuario).
9. [ ] Evitar degradación en casos con PDF nativo correcto.

## Fase 4 — Pruebas
10. [ ] Unit tests de detector/ruteo.
11. [ ] E2E con fixture real de CV escaneado:
    - texto útil extraído,
    - reducción de unknown técnico,
    - disminución de bloqueos por falta de evidencia.
12. [ ] Benchmark de tiempos de proceso con y sin fallback.

## Fase 5 — Operación
13. [ ] Telemetría de tasa de fallback OCR y calidad media.
14. [ ] Playbook de contingencia para entornos con dependencias OCR incompletas.

## Entregables
- Fallback OCR robusto activo en pipeline documental.
- Métricas de calidad OCR visibles para soporte.
- Suite de pruebas de regresión CV escaneado.
- Documento de operación y troubleshooting.
