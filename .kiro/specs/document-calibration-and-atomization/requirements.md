# Requisitos: Calibración Documental y Atomización de Domicilio

## Contexto
En la licitación de Paneles Solares (UNAQ) se observó sobre-detección documental (cientos de elementos no entregables). Esto bloquea el flujo de generación y degrada la confianza del usuario. En paralelo, el `domicilio_fiscal` está llegando como bloque único, lo que limita el llenado fino de formatos.

## Objetivo
1. Reducir ruido documental y priorizar entregables reales.
2. Estructurar domicilio fiscal en campos utilizables por generación documental.
3. Mantener trazabilidad auditable y precedencia canónica de datos.

## Alcance y división de entregables
- **Entregable A (Fase 1):** Calibración anti-ruido del flujo documental.
- **Entregable B (Fase 2):** Atomización de domicilio fiscal.
- La normalización avanzada de RFC/representante legal queda fuera de esta spec y se tratará en un bloque independiente.

## Requisitos funcionales

### R1 — Filtro Semántico Anti-Ruido
- El sistema debe separar con mayor precisión `entregables` versus `contenido informativo/normativo`.
- Debe evitar clasificar como `generar` elementos tipo normas de conducta, glosarios, avisos y reglas operativas sin documento asociado.
- Debe mantener evidencia de origen por ítem (`snippet`, fuente y razón de clasificación).

### R2 — Lista candidata operable para Fast Track
- La salida documental debe priorizar el carril de lista candidata rápida.
- Cada ítem debe llegar con `tipo_accion` y `confidence` para habilitar confirmación humana breve.
- Debe reducirse de manera sustancial la sobre-generación en el caso UNAQ.

### R3 — Atomización de domicilio fiscal
- Debe intentarse desglosar `domicilio_fiscal` en:
  - `calle`, `numero_exterior`, `numero_interior`, `colonia`, `municipio_alcaldia`, `estado`, `cp`.
- Debe preservarse siempre `domicilio_fiscal` original como respaldo.
- Si la atomización es incompleta o ambigua, el sistema debe marcar pendiente de confirmación (HITL) sin inventar datos.

### R4 — Precedencia canónica explícita
- La resolución final debe respetar:
  - `override_usuario > documento_normalizado > valor_original`.

### R5 — Trazabilidad auditable
- Deben persistirse snapshots y provenance en sesión/API para cada decisión relevante.
- Los ajustes no deben depender de notas manuales como fuente principal de auditoría.

## Requisitos no funcionales

### N1 — Eficiencia para 8GB VRAM
- No aumentar significativamente llamadas LLM en clasificación documental.
- Priorizar reglas/heurísticas deterministas antes de fallback LLM.

### N2 — Compatibilidad y no regresión
- No romper el flujo actual de análisis, go/no-go y generación.
- Debe existir comportamiento seguro en modo degradado.

## Criterios de aceptación
- Caso UNAQ reduce la lista candidata a un rango objetivo operativo (~12-15 documentos).
- `0` ítems normativos clasificados como `generar` en el escenario de prueba.
- En perfil empresa, `direccion_estructurada` se persiste sin perder `domicilio_fiscal`.
- En casos ambiguos de domicilio, el sistema solicita confirmación explícita en lugar de autocompletar incorrectamente.
