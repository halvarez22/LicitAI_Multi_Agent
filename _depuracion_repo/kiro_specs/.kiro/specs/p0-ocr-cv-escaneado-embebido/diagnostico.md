# Diagnóstico — P0 OCR CV Escaneado Embebido

## Síntoma observado en prueba
- CV PDF compartido no incrementó evidencia técnica utilizable.
- Bloqueos repetidos por `INCOMPLETE_TECHNICAL_DATA`.
- `unknown_ratio` técnico arriba de umbral de gate.

## Evidencia
- Error de procesamiento PDF dependiente de entorno (`poppler` ausente) en camino directo.
- Extracción textual mínima/no suficiente en documentos escaneados embebidos.
- Workarounds (TXT sintético, profile injection, override gate) permitieron avanzar, confirmando limitación de OCR y no de negocio.

## Causa raíz probable
1. Pipeline prioriza texto nativo y no siempre aplica fallback visual efectivo.
2. Dependencias OCR/PDF no robustas en todos los entornos.
3. Falta medición de calidad OCR para decidir rutas de procesamiento.

## Riesgo
- Alto (P0): pérdida de evidencia técnica y bloqueos en generación.
- Riesgo de propuesta incompleta o necesidad de intervención manual frecuente.

## Estado actual
- Hallazgo documentado y mitigado manualmente para cerrar prueba.
- No resuelto estructuralmente en flujo productivo.

## Hipótesis a validar en sprint
1. Fallback OCR visual reduce unknown técnico en CV escaneado real.
2. Clasificador técnico mejora con texto OCR normalizado.
3. El costo de procesamiento adicional es aceptable.
