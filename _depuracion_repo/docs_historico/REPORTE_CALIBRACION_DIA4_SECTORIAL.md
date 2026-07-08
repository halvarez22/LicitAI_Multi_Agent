# Reporte de Calibración Día 4

## Objetivo

Cerrar el ciclo de blindaje multisectorial con una lectura de calibración sobre:
- señales traslapadas entre sectores,
- umbrales de decisión (`mixto`/`indeterminado`),
- zonas grises que requieren refuerzo en v2.

Base de evidencia:
- implementación de clasificación sectorial en `AnalystAgent`,
- suite vertical México (`12/12` en verde),
- reglas conservadoras actualmente activas.

## Estado actual (resumen ejecutivo)

- Clasificador sectorial: **estable** y **auditable** (incluye `signal_code` + `snippet`).
- Cobertura validada: `obra_publica`, `salud`, `adquisiciones`, `servicios`.
- Política conservadora: en ambigüedad, prioriza `mixto`/`indeterminado` sobre sobreconfianza.
- Resultado operativo: reduce riesgo de clasificación alucinada y habilita explicación forense.

## Hallazgos de calibración

### 1) Señales traslapadas (riesgo de confusión)

Riesgos principales observados por diseño de patrones:

- **TIC vs Servicios**
  - Señales como `mesa de ayuda` o `SLA` pueden coexistir en licitaciones de soporte tecnológico.
  - Riesgo: clasificar `tic` como `servicios` cuando no aparecen anclas técnicas fuertes (`api`, `ciberseguridad`, `licenciamiento`).

- **Adquisiciones vs Salud**
  - `partidas`, `fichas técnicas` y `entrega de bienes` aparecen en ambos universos.
  - Desempate real en salud depende de señales específicas (`COFEPRIS`, `registro sanitario`, `carta fabricante`, `aviso funcionamiento`).

- **Obra Pública vs Servicios especializados**
  - Términos como `personal`, `supervisión` y `metodología` pueden aparecer en ambos.
  - Obra pública requiere anclas duras (`análisis de precios unitarios`, `catálogo de conceptos`, `programa de obra`).

### 2) Evaluación del umbral de confianza (`0.55`)

Lectura actual:

- El umbral favorece seguridad jurídica-operativa (evita falsas certezas).
- Con el set v1, `0.55` se comporta bien para casos con señales claras.
- En documentos híbridos o incompletos, el sistema cae correctamente a `mixto` o `indeterminado`.

Riesgo residual:

- En textos cortos con pocas señales, la confianza puede quedar baja aunque el sector sea correcto.
- Esto es aceptable en Fase actual (mejor duda explícita que error silencioso).

Recomendación:

- Mantener `0.55` en producción controlada.
- Revalorar a `0.52` solo si la suite v2 detecta exceso de `indeterminado` en casos claramente etiquetados.

### 3) Zonas grises (v2)

Brechas a reforzar:

- **TIC**: ampliar señales de nube, interoperabilidad, gestión de identidades, SOC/NOC.
- **Salud**: incluir más anclas regulatorias (BPM, farmacovigilancia, número de lote/caducidad con mayor peso contextual).
- **Adquisiciones**: distinguir mejor suministro general vs suministro especializado (insumos críticos).
- **Mixtas reales**: crear fixtures donde coexistan obra + suministro, o servicios + TIC, para calibrar delta de desempate.

## Recomendaciones accionables (Día 4)

1. **Matriz de señales v2**
   - Agregar 3 a 5 señales por sector con pesos moderados.
   - Definir señales “hard anchor” por vertical (alto peso, baja ambigüedad).

2. **Pruebas de traslape dirigidas**
   - Crear sub-suite `vertical_mexico_overlap` con casos ambiguos controlados.
   - Medir tasa de `mixto` esperada vs no esperada.

3. **Telemetría de calidad sectorial**
   - Registrar por sesión:
     - `sector_id`,
     - `confidence`,
     - top-3 `signal_code`,
     - bandera `mixto/indeterminado`.
   - Generar tablero semanal de drift sectorial.

4. **Calibración por etapa**
   - Etapa 1: mantener política conservadora actual.
   - Etapa 2: ajuste fino de pesos con evidencia de suite ampliada.
   - Etapa 3: activar sugerencias sectoriales downstream (Intake/DataGap) con feature flag.

## Criterios de salida para cierre de semana

- Suite vertical base: verde (cumplido).
- Reporte de calibración y plan v2: documentado (cumplido).
- Lista priorizada de mejoras: disponible para sprint siguiente (cumplido).

## Conclusión

El clasificador sectorial está listo para operación controlada y ya entrega valor real de negocio: **mejor precisión contextual por vertical con trazabilidad auditable**.  
La siguiente ganancia de calidad vendrá de robustecer zonas de traslape (especialmente `tic` vs `servicios`) y ampliar señales v2 con fixtures ambiguos de alta fidelidad.
