# Diseno Tecnico: Hardening de Prompts para Triage y Auditoria Legal

## 1. Contexto
El pipeline ya cuenta con enforcement determinista en codigo. Esta fase asegura que los prompts trabajen en sincronia con esa logica, minimizando drift entre lo que el LLM responde y lo que el backend valida.

## 2. Principios de Diseno
- **Contrato primero:** El prompt se adapta al parser productivo, no al reves.
- **Precedencia explicita:** Politicas y evidencia literal tienen prioridad sobre inferencia.
- **Explicabilidad por item:** Toda clasificacion debe exponer razon y evidencia.
- **HITL transaccional:** Las correcciones humanas deben poder convivir con reglas deterministas.

## 3. Arquitectura de Prompts

### 3.1 Prompt de Triage (Gemini Flash)
Objetivo: clasificar `law`, `jurisdiction`, `tender_category` con confianza y senales.

Elementos de hardening:
- Definir senales fuertes por jurisdiccion (ej. Queretaro) y pedir minimo de consistencia.
- Solicitar `confidence` y `signals_detected` para auditabilidad.
- Restringir salida a JSON estricto del schema.

Salida objetivo:
- `law`
- `jurisdiction`
- `tender_category`
- `confidence`
- `signals_detected` (lista corta)

### 3.2 Prompt de Auditoria (Gemini Pro)
Objetivo: extraer items auditables alineados a `must_have_policy`.

Elementos de hardening:
- Campo canonico obligatorio: `tipo_accion`.
- Campos de obligatoriedad dual:
  - `obligatorio_por_bases`
  - `obligatorio_por_marco_normativo`
- Bloque de razonamiento auditable por item:
  - `label_taxonomica`
  - `justificacion_clasificacion`
  - `snippet`
- Instruccion de precedencia:
  - si hay conflicto entre inferencia y politica, prevalece politica.

## 4. Contrato de Interoperabilidad (Prompt <-> Backend)
- El backend sigue consumiendo `tipo_accion`, `categoria`, `snippet`, `quality_flags`.
- Los nuevos campos de contexto legal deben ser aditivos, no sustitutos.
- Campos nuevos propuestos para salida del LLM deben mapearse sin romper la normalizacion actual.
- `TenderRouterService` debe consumir una interfaz real de `llm_service` (`LLMServiceClient.generate`) y no depender de funciones no exportadas.

## 5. Mapeo de Riesgos y Mitigaciones
- **Riesgo:** Drift de nombres de campo (`action` vs `tipo_accion`).
  - **Mitigacion:** instrucciones de salida cerrada + ejemplos negativos.
- **Riesgo:** sobre-clasificacion por keyword unica.
  - **Mitigacion:** requerir dos senales o una senal fuerte + evidencia literal.
- **Riesgo:** sobreforzado de `forced_by_must_have`.
  - **Mitigacion:** monitorear ratio de forzado y auditar `matched_on`.
- **Riesgo:** falla de infraestructura por drift de simbolos (ej. `get_llm_client` inexistente).
  - **Mitigacion:** integrar triage contra cliente LLM canonical del proyecto y agregar smoke A/B tras cambios.
- **Riesgo:** `RAG vacío` en host por `VECTOR_DB_URL` apuntando a hostname de Docker (`vector-db`).
  - **Mitigacion:** normalizar URL a `127.0.0.1` fuera de Docker en `VectorDbServiceClient`.
- **Riesgo:** caída de LLM en host por `LLM_URL` con hostname Docker (`llm-inference`).
  - **Mitigacion:** normalizar URL a `127.0.0.1` fuera de Docker en `LLMServiceClient`.

## 6. Observabilidad
Se recomienda consolidar en telemetria:
- `triage_law`, `triage_confidence`, `triage_signals_count`
- `must_have_recall`
- `forced_by_must_have_count`
- `forced_wrong_action_count`
- `informativo_rate_leg_fis`

## 7. Criterio de Cierre de Diseno
El diseno se considera cerrado cuando:
- prompt de triage y auditoria quedan versionados,
- contrato de salida queda alineado y validado en QA,
- prueba UNAQ cumple umbrales de recall/precision definidos por el equipo.
