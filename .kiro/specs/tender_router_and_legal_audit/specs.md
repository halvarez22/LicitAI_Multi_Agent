# Specs: Tender Router and Legal Audit (Fase 1 - Hardening)

## 1. Objetivo
Resolver la imprecisión del `ComplianceAgent` al clasificar documentos obligatorios como "informativos". Se busca transformar el agente de un lector pasivo a un **Perito Auditor** que valida contra un marco normativo específico.

## 2. Requerimientos Funcionales
- **RF1 - Triage Normativo:** El sistema debe identificar automáticamente la Ley Aplicable (LAASSP, LOPSRM, Ley Estatal), la Jurisdicción (Federal/Estatal) y la Categoría (Salud, Obra, etc.) en los primeros segundos del análisis.
- **RF2 - Matriz de Obligatorios (Must-Haves):** El sistema debe contar con una lista predefinida de documentos obligatorios por cada marco normativo (ej: En Querétaro, la Opinión Estatal es obligatoria).
- **RF3 - Clasificación Determinista:** Si un fragmento de texto coincide con un elemento de la Matriz de Obligatorios, el agente DEBE clasificarlo como `tipo_accion: generar` o `presentar_fisico`, nunca como `informativo`.
- **RF5 - Política de Acción Esperada por Etiqueta:** Cada `must_have` debe tener acción esperada (`presentar_fisico` para `LEG_`/`FIS_`, `generar` para `DECL_`/`TEC_`/`ECO_`) y aliases para matching semántico básico.
- **RF6 - Trazabilidad de Enforcement:** Si se fuerza reclasificación por matriz, el ítem debe incluir evidencia explícita (`forced_by_must_have`, `quality_flags`).
- **RF4 - Auditoría de Reglas Críticas:** El sistema debe extraer reglas de negocio específicas que causan descalificación (ej: el número de decimales permitidos en la propuesta económica).

## 3. Requerimientos Técnicos
- **RT1 - Pipeline de Dos Pasos:** Implementar un flujo secuencial: `Triage` -> `Análisis/Auditoría`.
- **RT2 - Optimización de Recursos:** Usar modelos locales ligeros para el Triage y modelos locales de alta capacidad (Ollama) para la Auditoría.
- **RT3 - Trazabilidad:** El resultado del triage debe persistirse en el estado de la sesión para ser consumido por todos los agentes downstream.
- **RT4 - Determinismo defensivo:** El enforcement de must-have no depende solo del prompt; se aplica en post-procesado map-reduce.

## 4. Criterios de Aceptación
- El sistema detecta correctamente la Ley de Querétaro en el PDF de la UNAQ.
- El sistema reduce los documentos marcados como "informativos" priorizando los anexos obligatorios identificados en la matriz.
- El sistema alerta sobre la falta de documentos obligatorios que no fueron encontrados en el texto pero que son requeridos por ley.
- Los must-have de tipo legal/fiscal no se reclasifican indebidamente a `generar`; se respeta la acción esperada por etiqueta.