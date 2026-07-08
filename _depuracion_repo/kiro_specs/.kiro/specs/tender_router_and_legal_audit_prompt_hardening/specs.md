# Specs: Hardening de Prompts Router + Legal Audit (Fase 2)

## 1. Objetivo
Endurecer la capa de prompts del flujo `Triage -> Auditoria` para que opere alineada con el contrato actual del backend, reduzca ambiguedades de clasificacion y mejore la trazabilidad de decisiones legales en casos como UNAQ.

## 2. Alcance
- Incluye ajustes de prompts para `TenderRouterService` (triage) y `ComplianceAgent` (auditoria).
- Incluye gobernanza de salida JSON y reglas de precedencia con `must_have_policy`.
- Incluye criterios de aceptacion y metricas para prueba de fuego UNAQ.
- Incluye correccion de integracion del cliente LLM en triage (`LLMServiceClient`) para habilitar corridas A/B.
- Incluye hardening de conectividad vectorial host/docker para evitar `RAG vacío` por resolución de `VECTOR_DB_URL`.
- No incluye cambios de arquitectura nuevos fuera del hardening de prompts.

## 3. Requerimientos Funcionales
- **RF1 - Contrato de salida estable:** El prompt de auditoria debe pedir explicitamente `tipo_accion` y evitar nombres alternos (`action`, `audit_list`) que no correspondan al parser productivo.
- **RF2 - Doble obligatoriedad:** Todo hallazgo debe poder distinguir:
  - `obligatorio_por_bases` (explicito en convocatoria),
  - `obligatorio_por_marco_normativo` (derivado de `must_have_policy`).
- **RF3 - Precedencia obligatoria:** El prompt debe declarar que la clasificacion final respeta:
  1) Usuario/HITL,
  2) evidencia literal de documento,
  3) politica `must_have_policy`,
  4) inferencia libre del modelo.
- **RF4 - Regla Queretaro robusta:** El triage no debe depender de una sola keyword; requiere senales fuertes y consistentes para fijar `LEY_QUERETARO`.
- **RF5 - Justificacion estructurada por item:** Cada item debe incluir razon corta de clasificacion y evidencia literal (`snippet`) usable para auditoria humana.
- **RF6 - Cero omisiones criticas:** Si una etiqueta must-have no aparece textual, el agente debe reportar omision explicita para revisarla en UI/HITL.
- **RF7 - Disponibilidad de triage en runtime:** El triage no debe fallar por imports/simbolos no exportados; el cliente LLM debe invocarse via API estable de `llm_service`.

## 4. Requerimientos No Funcionales
- **RNF1 - Determinismo observable:** Las salidas deben ser reproducibles y auditables (misma entrada, misma semantica de salida).
- **RNF2 - Compatibilidad backward:** No romper el contrato existente del `ComplianceAgent`.
- **RNF3 - Trazabilidad visible:** Mantener campo de procedencia de enforcement (`forced_by_must_have`, `quality_flags`).
- **RNF4 - Robustez anti-alucinacion:** Si falta evidencia literal, el prompt debe forzar marcadores de incertidumbre en vez de inventar.
- **RNF5 - Operabilidad A/B:** El sistema debe permitir corridas control/tratamiento sin bloqueos de infraestructura en etapa triage.

## 5. Criterios de Aceptacion
- El prompt de auditoria solo usa `tipo_accion` como campo operativo.
- Se observa separacion clara entre obligatoriedad por bases y por marco normativo.
- En UNAQ, la deteccion de documentos estatales obligatorios no queda degradada a `informativo`.
- Los logs y salida conservan evidencia de enforcement determinista.
- Se reduce la tasa de falsos informativos frente al baseline previo.

## 6. Metricas de Exito (Prueba UNAQ)
- `must_have_recall` >= objetivo definido por QA.
- `informativo_rate` en etiquetas `LEG_/FIS_` por debajo del baseline.
- `forced_by_must_have_count` dentro de rango esperado (ni cero sistemico ni sobre-forzado masivo).
- `wrong_action_on_forced` tendiendo a cero.
