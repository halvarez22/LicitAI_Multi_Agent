# Fase 2: Orquestador Adaptativo (MVP) 🧠

## Objetivo
Optimizar la ejecución del pipeline multi-agente seleccionando la ruta más eficiente según la complejidad del documento y activando mecanismos de parada temprana (short-circuit) ante riesgos detectados.

## Estrategias de Routing

Basado en el perfilado dinámico del documento, el orquestador selecciona una de las siguientes rutas:

| Tipo | Aplicabilidad | Stages Incluidas |
| :--- | :--- | :--- |
| **ANALYSIS_LIGHT** | Documentos simples (< 10 requisitos). | Analysis, Compliance, Formats, Packager. (Salta redactores pesados). |
| **COST_FOCUS** | Si se detecta prioridad en precios/cotizaciones. | Analysis, Compliance, Economic, EconomicWriter, Packager. |
| **DEFAULT_FULL** | Caso por defecto para licitaciones complejas. | Todos los agentes (DataGap, Technical, etc.). |

## Mecanismos de Short-Circuit (Reglas Tipadas)

El sistema evalúa reglas en puntos críticos para detener o desviar la ejecución sin usar `eval()` dinámico.

### Reglas Implementadas
1. **MISSING_CRITICAL_DATA**: Si el `DataGapAgent` marca un bloqueo, se detiene la secuencia para esperar entrada del usuario.
2. **LOW_CONFIDENCE_AVG**: Si el promedio de confianza de los análisis cae por debajo de 0.60, se dispara una acción de `ESCALATE`.
3. **TOO_MANY_LOW_CONF_ITEMS**: Si más de 3 campos críticos tienen baja confianza, se recomienda revisión humana.

---

## Seguridad y Configuración

### Flags de Control (Settings)
- `ADAPTIVE_ORCHESTRATOR_ENABLED`: Activa el modo adaptativo.
- `ADAPTIVE_PIPELINE_SAFE_MODE`: (Default: True). En este modo, el orquestador sugiere skips en logs pero **no se salta** ninguna etapa real para garantizar estabilidad.
- `ADAPTIVE_MAX_SKIPS`: Máximo de etapas que pueden saltarse en una sola ejecución.

### Metadata de Respuesta
La respuesta final incluye el bloque `metadata.pipeline_config` con trazabilidad completa de lo planeado vs lo ejecutado.

---

## Límites de Seguridad (Fail-Safe)
1. **Fallback a Full**: Si el perfilado falla o es ambiguo, el sistema siempre opta por `DEFAULT_FULL`.
2. **Prioridad de Modo**: Los modos manuales (`analysis_only`, `generation`) tienen prioridad sobre la optimización adaptativa.
3. **Escalamiento**: Ante dudas de confianza, el sistema prefiere `ESCALATE` (pedir ayuda) antes que `STOP` silencioso.
