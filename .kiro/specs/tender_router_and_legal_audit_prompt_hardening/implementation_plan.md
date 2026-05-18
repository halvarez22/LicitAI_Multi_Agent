# Plan de Implementacion: Hardening de Prompts Router + Legal Audit

## Fase 0 - Baseline y control
1. [ ] Congelar baseline UNAQ actual:
   - `must_have_recall`
   - `informativo_rate_leg_fis`
   - `forced_by_must_have_count`
   - conteo total de items extraidos
2. [ ] Definir umbrales de aceptacion para Go/No-Go con QA.

## Fase 1 - Hardening de Prompt de Triage
3. [x] Versionar prompt de triage (v2) con:
   - JSON estricto,
   - `signals_detected`,
   - reglas de clasificacion Queretaro por senales fuertes.
   - corregir integracion runtime de cliente LLM en `TenderRouterService` para evitar bloqueos por import.
4. [ ] Probar triage con 3 casos:
   - federal LAASSP,
   - estatal Queretaro,
   - caso ambiguo (esperado: confianza baja + explicacion).

## Fase 2 - Hardening de Prompt de Auditoria
5. [x] Versionar prompt de auditoria (v2) con contrato cerrado:
   - `tipo_accion` obligatorio,
   - `obligatorio_por_bases`,
   - `obligatorio_por_marco_normativo`,
   - `justificacion_clasificacion`.
6. [ ] Agregar bloque de precedencia explicita:
   - HITL > evidencia literal > politica > inferencia.
7. [ ] Incluir ejemplos positivos/negativos para:
   - `presentar_fisico` en `LEG_`/`FIS_`,
   - `generar` en anexos editables.

## Fase 3 - Validacion funcional y legal
8. [~] Correr pipeline completo UNAQ con prompts v2.
   - Estado: corrida A/B iniciada; se detecto y resolvio bloqueo de import en triage.
   - Estado: se detecto `RAG vacío` por conectividad vectorial host/docker; aplicado hardening en `VectorDbServiceClient`.
   - Estado: se detecto fallo de resolución LLM host/docker (`llm-inference`); aplicado hardening en `LLMServiceClient`.
9. [ ] Validar checklist de hallazgos:
   - deteccion de obligatorios estatales,
   - reduccion de falsos informativos,
   - trazabilidad de forzados con `matched_on`.
10. [ ] Revisar con Antigravity y Gemini discrepancias de clasificacion.

## Fase 4 - Cierre y despliegue controlado
11. [ ] Emitir reporte comparativo baseline vs v2.
12. [ ] Si cumple umbrales, activar prompts v2 como default.
13. [ ] Documentar rollback rapido a v1 (feature flag o versionado de prompt).

## Entregables
- Prompt Triage v2 versionado.
- Prompt Auditoria v2 versionado.
- Matriz de resultados UNAQ (antes/despues).
- Dictamen tecnico de validacion firmado por equipo.
