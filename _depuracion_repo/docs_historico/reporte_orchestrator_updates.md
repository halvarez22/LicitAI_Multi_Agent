# Reporte de Ajustes: E2E Orquestador y Agentes (Refactorización de Negocio)

Se han aplicado exitosamente los ajustes críticos solicitados en el diseño del Orquestador para respetar la lógica de la evaluación E2E.

## 1. Modificaciones Aplicadas

| Módulo/Archivo | Ajuste Realizado | Impacto |
| --- | --- | --- |
| `backend/app/agents/orchestrator.py` | **Política B Revisada:** Se restringió el `return` temprano tras Compliance. Solo si el estado es estricatamente `"error"` (excepción en código, LLM caído) se aborta la ejecución con `COMPLIANCE_ERROR`. Si es `"fail"` o `"partial"`, la iteración continúa y se invoca a *EconomicAgent*. | Flexibiliza el proceso para dejar continuar licitaciones donde un bloque menor haya fallado, preservando resultados parciales. |
| `backend/app/agents/orchestrator.py` | Se añadió `"session_id": session_id` a la respuesta del orquestador cuando se rechaza una solicitud por **INVALID_MODE**. | Garantiza consistencia del payload para FastAPI y componentes de tracking E2E. |
| `backend/app/agents/orchestrator.py` | Parada por DataGapAgent (`waiting_for_data`): Se añadieron los campos `results` copiando la variable `execution_results`. | Cuando la *Fase 2* pide datos a humanos, el cliente Frontend no perderá el trabajo cobrado en la *Fase 1*. |
| `backend/tests/test_orchestrator_behavior.py` | Se crearon los tests `test_orchestrator_compliance_partial_aun_invoca_economic` y `test_orchestrator_compliance_fail_aun_invoca_economic` que fuerzan los mocks de Compliance y validan que `EconomicAgent` sea invocado una vez (`assert_awaited_once`). | Soldadura técnica al CI/CD. Garantiza que futuros cruces de código no eliminen esta regla de negocio en ambos escenarios. |

## 2. Pruebas y Resultados (Test de Integridad)
Se ejecutó la suite de tests unitarios:
```bash
python -m pytest tests/test_orchestrator_behavior.py tests/test_compliance_llm_telemetry.py -v
```
**Resultado:** Todos los tests en verde. Toda la batería de telemetría y comportamiento del orquestador está completada.

---

## 3. Documentación Operativa (Matriz de Decisiones E2E)

Para mantener al equipo (y futuras inteligencias integradas) en sintonía con las nuevas reglas, estas son las tablas de verdad operacionales:

### Matriz MODO -> Fases Ejecutadas
El modo dicta cómo el Orquestador canalizará a los agentes serialmente.

| `company_data.mode` | ¿Fase 1 (A-C-E)? | ¿Fase 2 (D-R-F-E-E-G)? | Comportamiento esperado |
| --- | --- | --- | --- |
| `"analysis_only"` | ✅ SÍ | ❌ NO | Realiza la autopsia del documento y se detiene aportando `results.analysis`, `compliance` y `economic`. Ideal para despliegue inicial en UI. |
| `"generation_only"` | ❌ NO | ✅ SÍ | Omite la Fase 1. Depende exclusivamente de recuperar estados por RAG/Memoria para forzar generación de anexos y declaratorias. |
| `"full"` | ✅ SÍ | ✅ SÍ | Corre todas las fases en un solo tick, pausando solo si faltan métricas de precios u otra data dura de empresa. |
| *(Cualquier otro)* | ❌ NO | ❌ NO | Falla rápido (Fail-fast) respondiendo `"status": "error"` con el motivo exacto de modo irreconocible (Punto de fallo 2 ajustado hoy). |

*Agentes Fase 1:* Analyst, Compliance, Economic.
*Agentes Fase 2:* DataGap, TechnicalWriter, Formats, EconomicWriter, Packager, Delivery.

### Matriz: Estado COMPLIANCE -> ¿Se Detiene el pipeline?
Define cuándo el *Orquestador* se rinde versus cuándo avanza al *EconomicAgent*.

| `execution_results["compliance"]["status"]` | ¿Invoca a EconomicAgent? | `orchestrator_decision.aggregate_health` Final | Estatus HTTP Raíz | 
| --- | --- | --- | --- |
| `"success"` | **SÍ** | `"ok"` | `success` |
| `"partial"` | **SÍ** | `"partial"` (*Degradado* - e.g., el LLM encontró requerimientos pero una zona dio Timeout) | `success` |
| `"fail"` | **SÍ** | `"failed"` (*Incompleto* - El reporte de compliance falló validaciones y métricas, pero Phase 1 continúa para extraer economía) | `success` |
| `"error"` | **NO** (Bloqueo) | `"failed"` (*Quiebre de máquina* - LLM down, KeyError severo). `stop_reason = COMPLIANCE_ERROR`. | `success` |

> **NOTA CRÍTICA FRONTEND:** Incluso ante fallas severas de un Agente (e.g. COMPLIANCE_ERROR), el `status` principal HTTP retornará `"success"` (por diseño legado del backend para no romper los clientes). El Frontend **DEBE** interrogar el campo `aggregate_health` o los estatus individuales en `agent_status` de la rama `orchestrator_decision` para pintar los iconos de error correctos.

> **IMPORTANTE FRONTS Y QA:** Para observar este comportamiento E2E al consumir `localhost:8001`, asegúrense de cerrar / reiniciar el contenedor del servicio luego de esta actualización. Uvicorn en frío no carga scripts cacheados.
