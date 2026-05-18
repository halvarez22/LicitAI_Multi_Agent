# REPORTE DE CERTIFICACION v1.2c

## 1) Resumen Ejecutivo

La calibracion del Fill Quality Gate alcanza el estandar objetivo de esta fase:

- Precision global: **1.0**
- Recall global: **1.0**
- Blocking match rate: **1.0**

Resultado: el sistema bloquea errores reales sin introducir ruido operativo en el dataset objetivo de calibracion, conservando guardas de seguridad para produccion.

## 2) Alcance Certificado

Se certifica el bloque de calibracion sobre:

- `backend/app/services/fill_quality_calibration.py`
- `backend/app/services/document_fill_quality_gate.py`
- `backend/scripts/run_fill_quality_calibration.py`
- `backend/tests/fixtures/fill_quality_calibration/*`
- `backend/tests/test_fill_quality_calibration.py`
- `backend/tests/test_document_fill_quality_gate.py`

Reporte de evidencia:

- `backend/scratch/fill_quality_calibration_report_v1_2c.json`

## 3) Hitos Tecnicos Entregados

### 3.1 Motor de policy con condiciones avanzadas

Se habilita tuning por:

- `error_type`
- `field_key`
- `stage`
- `template_id`
- `when_master_profile`
- `min_provenance_confidence`
- `when_signal`

Esto permite políticas contextuales, trazables y reversibles.

### 3.2 Señales de confianza basadas en evidencia numerica (v1.2c)

Se implementan señales positivas derivadas directamente del documento materializado:

- `arithmetic_match`
- `consistency_pass`
- `arithmetic_delta`
- `tolerance`

La logica valida `subtotal + iva == total` con tolerancia controlada para redondeo.

### 3.3 Guardia rigida de negocio

Se mantiene innegociable:

- En etapa economica, `placeholder_detected` **nunca** se ignora.

Esto evita sobreajuste peligroso del tuning.

### 3.4 Robustez operativa en Windows

Se corrigen bloqueos de archivos temporales:

- cierre explicito de workbooks (`wb.close()`),
- limpieza best-effort con `mkdtemp + rmtree(ignore_errors=True)`.

## 4) Resultado de Calibracion (v1.2c)

Comparativo reportado:

- Baseline: precision 0.2632, recall 1.0
- Tuned v1.2c (policy v1.2b + señales numericas): precision 1.0, recall 1.0

Lectura:

- Se elimina ruido de falsos positivos en el set objetivo.
- Se mantiene cobertura total de hallazgos esperados.
- Se preserva semantica de bloqueo sin degradacion.

## 5) Controles de Calidad Ejecutados

Pruebas automatizadas ejecutadas:

- `tests/test_document_fill_quality_gate.py`
- `tests/test_fill_quality_calibration.py`

Estado final:

- Todas las pruebas en verde en la corrida de certificacion.
- Sin errores de lint en los archivos modificados.

## 6) Riesgos Residuales

Aunque el resultado del dataset objetivo es optimo, se documentan riesgos normales de operacion:

1. **Sobreajuste de laboratorio**: performance puede variar con documentos reales no representados.
2. **Deriva por plantillas nuevas**: nuevos formatos pueden requerir ajustes de policy.
3. **Calidad de OCR**: ruido extremo en extraccion puede afectar señales de consistencia.

Mitigacion:

- mantener corrida periodica de calibracion,
- versionar policy,
- introducir casos reales anonimizados de manera continua.

## 7) Recomendacion de Rollout

Se recomienda avanzar a rollout controlado:

1. `audit` con telemetria completa por 3-5 dias operativos.
2. `enforce parcial` en reglas criticas (placeholders y faltantes duros).
3. `enforce ampliado` segun KPIs de falso bloqueo.

## 8) Siguiente Fase Recomendada

### Fase 5 — Telemetria Real (post-certificacion)

Objetivo:

- alimentar el laboratorio de calibracion con sesiones reales anonimizadas,
- medir drift de precision/recall por sector y tipo documental,
- ajustar policy por evidencia de produccion.

Entregables sugeridos:

- dataset incremental de casos reales anonimizados,
- tablero semanal de calidad de gate,
- protocolo de ajuste y rollback por `policy_version`.

## 9) Veredicto Final

La calibracion **v1.2c queda certificada** para paso a produccion controlada.

El Fill Quality Gate alcanza el objetivo de negocio del sprint:

- evitar propuestas con errores reales,
- reducir interrupciones innecesarias al usuario,
- sostener trazabilidad forense para auditoria y mejora continua.
