# Estándar de desarrollo: aplicaciones enterprise con verdad canónica, HITL y trazabilidad

Este documento consolida el patrón de producto y arquitectura validado en LicitAI (Sprints 1–4.1). Sirve como **referencia normativa** para replicar el mismo nivel de excelencia en **cualquier aplicación** del portafolio: basta con exigir a humanos e IA que sigan estos principios y la checklist de cierre.

---

## 1. Visión en una frase

> **Separar la “verdad de negocio” de la “opinión del modelo”**: persistir una representación canónica auditable, gobernar validaciones con política explícita, permitir corrección humana transaccional con precedencia clara, y mostrar en la UI **de dónde salió cada dato** (sin caja negra).

---

## 2. Los cinco pilares (obligatorios en apps de decisión / datos sensibles)

| Pilar | Qué significa | Señal de que está bien |
|--------|----------------|-------------------------|
| **Verdad canónica** | Un esquema único versionado donde convergen ingestas heterogéneas (Excel, CSV, API, formularios). | Hay `schema_version`, merge idempotente por entidad/documento, resúmenes agregados y señales de calidad (placeholders, ceros, etc.). |
| **Gobernanza de validaciones** | Las reglas no son solo código duro: hay mapeo error→UX, severidad ajustable por contexto y auditoría de política. | `error_type` estable, mensajes humanos, presets (estricto/flexible), historial de cambios de política. |
| **Chat / UI transaccional** | El usuario puede **corregir el sistema** en el canal natural (chat o formulario), no solo leer errores. | Overrides con `raw_query`, revalidación automática, limpieza coherente de pendientes al resolverse bloqueos. |
| **Cascada de precedencia explícita** | Orden documentado y aplicado en código: qué fuente gana cuando hay conflicto. | Una sola función o capa que aplica: *usuario directo > documento normalizado > catálogo maestro > inferencia (LLM/RAG)*. |
| **Procedencia visible** | Cada valor crítico expone **origen** en API y en UI (badge, tooltip, modal). | Objeto `provenance_ui` (o equivalente) por ítem; mismos iconos/leyendas en chat y paneles. |

---

## 3. Patrones por capa

### 3.1 Backend

1. **Normalización**
   - Entrada: formatos múltiples → salida: estructura canónica única.
   - Incluir: trazas (`doc_id`, `row_index`, `sheet`, etc.), `confidence`, categorías de negocio, inferencia semántica cuando aplique (evitar doble conteo, tolerancias híbridas documentadas).

2. **Validación**
   - Motor determinista donde sea posible; LLM solo donde no haya regla verificable.
   - Bloqueos vs advertencias explícitos; nunca mezclar “mensaje técnico crudo” con lo que ve el usuario sin pasar por un **servicio de mapeo** (plantillas + contexto).

3. **Política dinámica**
   - Resolución de severidad por contexto (sesión, entidad regulada, feature flags).
   - Conjuntos documentados de reglas **nunca relajables** (integridad, firma, consistencias críticas).

4. **Sesión y auditoría**
   - Historial de overrides: `economic_user_overrides` (ejemplo) con `source`, `raw_query`, timestamp implícito.
   - Estado “aplanado” para agentes: `economic_user_inputs` (ejemplo) para consumo O(1).

5. **APIs HITL**
   - Acknowledge, justificación, telemetría, revalidación explícita tras cambios de datos.

### 3.2 Frontend

1. **Misma semántica en todos los superficies**
   - Chat, panel de entrega, administración: mismos colores/íconos para Chat / Documento / Catálogo / Inferencia.

2. **Feedback de sistema**
   - Progreso real en jobs largos (porcentaje + mensaje), no mensajes estáticos que parezcan cuelgue.

3. **Accesibilidad cognitiva**
   - Tooltips legibles (no solo `title` nativo si el producto es premium); listas acotadas + scroll para listas largas.

### 3.3 Operaciones

1. **Playbook de despliegue**
   - Preflight (servicios healthy), variables críticas explicitadas, smoke E2E, rollback, scripts de limpieza puntual.

2. **Observabilidad**
   - Logs estructurados en producción; correlación `session_id` / `correlation_id`; tiempos por etapa del pipeline.

---

## 4. Checklist para una aplicación nueva

Antes de dar por “lista” una funcionalidad que toca datos de negocio:

- [ ] ¿Existe **capa canónica** con versión de esquema y merge idempotente?
- [ ] ¿Las validaciones tienen **`error_type` estable** y mensajes humanos centralizados?
- [ ] ¿Hay **política** (estricto/flexible) con auditoría o trazabilidad de cambios?
- [ ] ¿El usuario puede **corregir datos** por el canal principal y eso **persiste** y **revalida**?
- [ ] ¿La **cascada de precedencia** está escrita y centralizada en código?
- [ ] ¿Cada ítem crítico expone **`provenance_ui`** (o equivalente) en API y en UI?
- [ ] ¿Existe **playbook** mínimo: env vars, healthchecks, smoke, rollback?

---

## 5. Prompt maestro para IA (copiar y adaptar)

Usar como prefijo o sección fija al encargar una app nueva:

```text
Construye la aplicación aplicando el estándar ENTERPRISE_CANONICO_HITL (ver docs/ESTANDAR_ENTERPRISE_CANONICO_HITL.md en el repo de referencia o el documento equivalente en este proyecto):

1) Verdad canónica: esquema versionado, normalización desde fuentes heterogéneas, merge idempotente, señales de calidad.
2) Gobernanza: validaciones con error_type, UX humanizada, política dinámica y reglas no negociables documentadas.
3) HITL transaccional: el usuario corrige en el canal natural; overrides auditables (raw_query + source); revalidación automática.
4) Cascada de precedencia explícita en código: Usuario > Documento normalizado > Catálogo > Inferencia LLM/RAG.
5) Procedencia visible: provenance_ui por ítem; misma semántica visual en chat y paneles.
6) Operación: variables críticas nombradas, healthchecks, smoke E2E, estrategia de rollback.

No entregues solo “funciona en demo”: entrega trazabilidad, política y UX de confianza.
```

---

## 6. Referencia de implementación en este repositorio (LicitAI)

| Área | Ubicación orientativa |
|------|------------------------|
| Normalización canónica | `backend/app/services/economic_normalizer.py`, `merge_normalized_payload` |
| Ingesta tabular / CSV | `backend/app/services/document_excel_ingest.py`, `document_csv_ingest.py` |
| Mapeo validación → UX | `backend/app/contracts/validation_mapping.json`, `validation_service.py` |
| Política dinámica | `backend/app/services/validation_policy_service.py`, rutas en `sessions.py` |
| Chat transaccional + procedencia | `backend/app/agents/chatbot_rag.py` |
| Cascada + provenance en propuesta | `backend/app/agents/economic.py` |
| UI procedencia panel | `frontend/src/components/DeliveryPanel.jsx` |
| UI procedencia chat | `frontend/src/App.jsx` |
| Playbook operativo | `DEPLOY_HARDENING_PLAYBOOK.md` |
| Variables backend | `backend/ENV_VARS.md` |

*(Las rutas son ejemplos concretos; en otro repo se replican los **conceptos**, no necesariamente los nombres de archivos.)*

---

## 7. Evolución del estándar

- **Versión del documento:** incrementar cuando cambien los pilares o la cascada obligatoria.
- **Por producto:** se puede añadir un anexo (ej. “sector salud”, “fintech”) con reglas `VALIDATION_STRICT_ENTITIES` o equivalentes.

---

## 8. Resumen ejecutivo para liderazgo

Este estándar reduce riesgo legal y operativo: menos datos silenciosamente incorrectos, más **explicabilidad** ante auditoría, y menos fricción del usuario frente a sistemas multi-agente. La inversión en capa canónica y procedencia se paga en confianza y en tiempo de soporte.
