# SPEC — P0 OCR CV Escaneado Embebido

## Objetivo
Permitir extracción confiable de CVs y documentos técnicos en PDF escaneado/embebido para reducir `unknown_ratio` y evitar bloqueos `INCOMPLETE_TECHNICAL_DATA`.

## Contexto de negocio
- En licitaciones reales, CVs y constancias suelen venir como imagen escaneada.
- Sin extracción de texto robusta, el sistema pierde evidencia técnica crítica.

## Problema actual
- PDFs con poco/no texto nativo no alimentan adecuadamente el pipeline técnico.
- Esto eleva unknown y detiene generación documental.

## Alcance
1. Detección automática de PDF escaneado o con texto insuficiente.
2. Fallback OCR visual por página.
3. Métrica de calidad OCR por documento/página.
4. Integración de texto OCR al índice y a clasificación técnica.

## Fuera de alcance
- Entrenamiento de modelos OCR propios.
- Cambios extensivos de interfaz fuera de indicadores esenciales.

## Requisitos funcionales
1. Si `text_native` es insuficiente, activar OCR visual automáticamente.
2. Guardar texto OCR y metadatos de calidad por página.
3. El contenido OCR debe participar en RAG y extracción técnica.
4. Registrar fuente de texto (`native`, `ocr_visual`, `mixed`) por documento.

## Requisitos no funcionales
- Robustez ante PDFs de baja calidad.
- Tiempos de proceso aceptables para operación.
- Trazabilidad de calidad para debugging.

## Criterios de aceptación
1. Con fixture de CV escaneado:
   - extracción de texto no vacío y semánticamente útil.
   - reducción de unknown técnico vs baseline sin OCR.
2. En PDFs con texto nativo:
   - no degradar precisión ni tiempos significativamente.
3. Corrida de generación no debe bloquearse por ausencia artificial de evidencia técnica cuando el CV sí contiene información.

## Métricas de éxito
- `technical_unknown_ratio` baja al menos 20-30% en casos con CV escaneado.
- tasa de bloqueos `INCOMPLETE_TECHNICAL_DATA` por OCR baja de forma sostenida.
