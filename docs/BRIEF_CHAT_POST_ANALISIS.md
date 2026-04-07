# Brief: Chat post-análisis y guía de insumos faltantes

Documento de implementación para alinear frontend, backend y UX. Objetivo: dar certeza de que las bases fueron aprendidas y un flujo conversacional inteligente para completar datos pendientes.

---

## 1. Objetivo de producto

Tras **analizar las bases** (y cuando el backend indique que faltan insumos), la aplicación debe:

1. Transmitir **explícitamente** que las bases ya fueron procesadas / indexadas (RAG) y que el dictamen refleja ese análisis.
2. Usar el **panel de chat** como canal principal con un mensaje del asistente del estilo: *«Terminé el análisis de las bases; para continuar necesito que me proporciones…»* y la **lista de datos faltantes** cuando aplique.
3. Soportar **intake incremental**: el usuario envía un dato → el sistema lo **registra y persiste** → el asistente **continúa solicitando** lo pendiente hasta cerrar la cola (comportamiento ya parcialmente implementado en backend para expediente vía `pending_questions`).

---

## 2. Estado actual del código (referencia)

| Pieza | Ruta | Comportamiento relevante |
|--------|------|---------------------------|
| Respuesta del pipeline | `backend/app/api/v1/routes/agents.py` → `AgentExecutionResponse` | `status`, `chatbot_message`, `missing_fields`, `data` |
| Orquestador | `backend/app/agents/orchestrator.py` | `waiting_for_data` + `chatbot_message` por gap económico; `missing_fields` en gap de datos (fase generación) |
| Lista de faltantes + sesión | `backend/app/agents/data_gap.py` | `pending_questions`, `current_question_index` en sesión (`_save_pending_questions`) |
| Intake por chat | `backend/app/agents/chatbot_rag.py` | Modo `DATA_INTAKE`: guarda en empresa, avanza índice, formula siguiente pregunta |
| Chat UI | `frontend/src/App.jsx` | `chatMessages`, panel «EXPERTO RAG»; solo `triggerGeneration` trata `waiting_for_data`; estado vacío desalentador |
| Auditoría | `frontend/src/App.jsx` → `triggerFullAudit` | No ramifica por `waiting_for_data` ni inyecta `chatbot_message` |

---

## 3. Tareas obligatorias — Frontend

**Archivo principal:** `frontend/src/App.jsx`.

### 3.1 `triggerFullAudit` (`POST /api/v1/agents/process`, `company_data.mode: analysis_only`)

Tras el `axios.post`, **ramificar** según `res.data.status`:

- **`success`**
  - Mantener: `processAuditResults(res.data.data)`, persistir dictamen, `fetchSources`.
  - **Añadir** mensaje de bot con texto que confirme fin de análisis e indexación, por ejemplo:  
    *«Análisis de bases completado. El dictamen forense está actualizado y la información ya está indexada para consultas. Si necesitas generar documentos o completar datos del expediente, te iré guiando por este chat.»*

- **`waiting_for_data`**
  - No asumir solo `success`.
  - Si `res.data.data` existe, construir dictamen con `processAuditResults(res.data.data)` cuando incluya `analysis` / `compliance` / `economic`.
  - **Añadir** a `chatMessages` un mensaje `sender: 'bot'`, `text: res.data.chatbot_message` (fallback si es null), **`isGlow: true`**.
  - Opcional: enriquecer con `res.data.missing_fields` si se desea lista explícita además del markdown de `chatbot_message`.

### 3.2 Panel de chat (copy y visibilidad)

- Sustituir el mensaje vacío *«Inicia la generación para activar al experto de datos»* por copy neutral, p. ej.: *«El experto puede ayudarte con las bases y con los datos que falten para avanzar.»*
- Tras mensajes importantes del asistente (confirmación post-auditoría o `waiting_for_data`), **destacar** el panel: `scrollIntoView`, pulso en borde, o ancho temporal del `aside` derecho — coherente con estilos inline existentes (sin Tailwind).

### 3.3 `handleSendMessage` (`POST /chatbot/ask`)

- Asegurar envío de **`company_id: selectedCompanyId`** cuando exista (requerido para `DATA_INTAKE` en `ChatbotRAGAgent`).
- Si hay cola de preguntas pendientes en sesión pero **no** hay empresa seleccionada, mostrar aviso claro (`alert` o mensaje bot): *«Selecciona una empresa en la barra superior para guardar tus datos.»*

### 3.4 Reutilización

- Extraer helper, p. ej. `pushAssistantGuidance({ text, isGlow, missingFields })`, compartido entre `triggerFullAudit` y `triggerGeneration` para evitar duplicación.

---

## 4. Tareas recomendadas — Backend / contrato

### 4.1 Gap económico vs cola de chat

Hoy `EconomicAgent` (`backend/app/agents/economic.py`) devuelve `waiting_for_data` con `message` y `missing_prices`, pero **no** alimenta `pending_questions` como `DataGapAgent`.

- **Opción A (mínima):** La UI muestra `chatbot_message` y, si existe, una tarjeta o lista desde `res.data.data.economic.missing_prices` con instrucción de catálogo / precios en el módulo de empresa.
- **Opción B (completa):** Serializar ítems con precio faltante en estructura compatible con el chatbot (`field`, `label`, `question`, `document_hint`), persistir en sesión y extender `_handle_data_intake` para escribir en catálogo o perfil según tipo.

### 4.2 Re-análisis

Tras subir documentos y volver a «Analizar bases», `DataGapAgent` recalcula al ejecutar generación; verificar que no queden `pending_questions` obsoletos sin documentar (re-ejecución de `agents/process` en modo adecuado).

### 4.3 Tests

- Test de orquestador o API: respuesta `waiting_for_data` incluye `chatbot_message` cuando corresponde.
- Smoke manual: generación con perfil incompleto → mensaje en chat → respuesta corta → verificar `master_profile` en BD y siguiente pregunta del bot.

---

## 5. Criterios de aceptación

- [ ] Tras **Analizar bases** con `status: success`, el chat muestra confirmación de análisis completado e indexación disponible para el experto.
- [ ] Tras **Analizar bases** con `status: waiting_for_data`, el chat muestra `chatbot_message` con resaltado (`isGlow`), sin perder dictamen parcial si `data` viene poblado.
- [ ] El estado vacío del chat no implica que solo «Generar» activa al experto.
- [ ] Con `pending_questions` en sesión, las respuestas del usuario se persisten y el bot solicita el siguiente campo (flujo existente en `chatbot_rag.py`).
- [ ] Sin `company_id`, el usuario recibe mensaje explícito al intentar aportar datos.

---

## 6. Archivos a tocar (resumen)

| Archivo | Acción |
|---------|--------|
| `frontend/src/App.jsx` | Ramas en `triggerFullAudit`; copy del chat; foco visual; helper; validación `company_id` |
| Opcional | `backend/app/agents/economic.py`, `backend/app/agents/chatbot_rag.py` | Opción B: cola para precios |
| Opcional | `frontend/src/utils/auditSummary.js` | Texto/UI para gap económico fuera del mensaje markdown |

---

## 7. Restricciones del proyecto (LicitAI)

- Mensajes y documentación orientados al usuario en **español**.
- Frontend: **sin Tailwind**; mantener patrones de estilo del código actual.
- Cambios al contrato `AgentExecutionResponse` solo con actualización del cliente y esquemas Pydantic en `backend/app/api/schemas/responses.py`.

---

## 8. Referencias rápidas de API

- `POST /api/v1/agents/process` — cuerpo: `session_id`, `company_id`, `company_data` (p. ej. `{ "mode": "analysis_only" }` o `"generation_only"`).
- `POST /api/v1/chatbot/ask` — debe incluir `session_id`, `query`, `company_id` cuando aplique intake.

---

*Versión: 1.0 — alineado con el repositorio LicitAI (FastAPI + React/Vite).*
