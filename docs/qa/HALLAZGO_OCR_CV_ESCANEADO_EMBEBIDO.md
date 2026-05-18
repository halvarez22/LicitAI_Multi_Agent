# Hallazgo: OCR de CV escaneado embebido en PDF

## Contexto

- Flujo: generación documental end-to-end (licitación vigilancia ISSSTE).
- Sesión de referencia: `unaq_final_d41d7dea`.
- Resultado observado: el CV en PDF con imágenes escaneadas embebidas no aporta texto suficiente al pipeline técnico.

## Problema

La app no está resolviendo de forma confiable documentos CV en PDF cuya información está en imágenes escaneadas embebidas.  
Esto reduce evidencia técnica utilizable y puede sostener bloqueos tipo `INCOMPLETE_TECHNICAL_DATA`.

## Impacto

- Aumenta `unknown_ratio` en clasificación técnica.
- Dificulta cierre de propuesta técnica sin intervención manual.
- Ralentiza operación en escenarios reales donde los CV vienen escaneados.

## Criterio de calidad esperado (objetivo producto)

La app debe ser capaz de extraer texto útil desde CV escaneados embebidos en PDF con calidad suficiente para:

1. identificar experiencia/capacitación/equipamiento,
2. reducir unknown técnico,
3. habilitar generación documental sin bloqueo espurio.

## Acciones pendientes (post-prueba)

1. Incorporar fallback OCR robusto para PDFs escaneados embebidos (incluyendo conversión de páginas a imagen).
2. Medir calidad OCR por página (score mínimo y señal de legibilidad).
3. Enriquecer enrutamiento documental para CV:
   - priorizar extractor OCR visual cuando el PDF no trae texto nativo.
4. Agregar prueba E2E con fixture de CV escaneado:
   - assert de texto mínimo extraído,
   - assert de disminución de unknown técnico respecto a baseline.

## Prioridad

- Prioridad: `P0` de robustez documental para operación en campo.
